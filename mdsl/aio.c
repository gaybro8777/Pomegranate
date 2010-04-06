/**
 * Copyright (c) 2009 Ma Can <ml.macana@gmail.com>
 *                           <macan@ncic.ac.cn>
 *
 * Armed with EMACS.
 * Time-stamp: <2010-04-04 16:32:23 macan>
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
 *
 */

#include "hvfs.h"
#include "xnet.h"
#include "mdsl.h"
#include "ring.h"
#include "lib.h"

#define MDSL_AIO_SYNC_SIZE_DEFAULT      (8 * 1024 * 1024)
#define MDSL_AIO_MAX_QDEPTH             (8)

struct aio_mgr
{
    struct list_head queue;
    xlock_t qlock;
    sem_t qsem;
    u64 sync_len;
    sem_t qdsem;                /* pause the submiting! */
    u64 pending_writes;
};

struct aio_thread_arg
{
    int tid;
};

struct aio_request
{
    struct list_head list;
    void *addr;
    size_t len;
    size_t mlen;
    loff_t foff;
    int type;
    int fd;
};

static struct aio_mgr aio_mgr;

#define MDSL_AIO_QDCHECK_LOCK           0
#define MDSL_AIO_QDCHECK_UNLOCK         1

void __mdsl_aio_qdcheck(int flag)
{
    if (flag == MDSL_AIO_QDCHECK_LOCK) {
        sem_wait(&aio_mgr.qdsem);
    } else if (flag == MDSL_AIO_QDCHECK_UNLOCK) {
        sem_post(&aio_mgr.qdsem);
    }
}

/*
 * @addr: address of the memory region
 * @len:  data length
 * @mlen: memory region length
 * @foff: file offset
 * @type: type of the aio request
 * @fd:   file descriptor act on
 */
int mdsl_aio_submit_request(void *addr, u64 len, u64 mlen, loff_t foff, 
                            int type, int fd)
{
    struct aio_request *ar;

    ar = xzalloc(sizeof(*ar));
    if (!ar) {
        hvfs_err(mdsl, "xzalloc() struct aio_reqesut faield.\n");
        return -ENOMEM;
    }
    ar->addr = addr;
    ar->len = len;
    ar->mlen = mlen;
    ar->foff = foff;
    ar->type = type;
    ar->fd = fd;

    INIT_LIST_HEAD(&ar->list);
    xlock_lock(&aio_mgr.qlock);
    list_add_tail(&ar->list, &aio_mgr.queue);
    xlock_unlock(&aio_mgr.qlock);

    atomic64_inc(&hmo.prof.storage.aio_submitted);
    
    return 0;
}

void mdsl_aio_start(void)
{
    __mdsl_aio_qdcheck(MDSL_AIO_QDCHECK_LOCK);
    sem_post(&aio_mgr.qsem);
}

int __serv_sync_request(struct aio_request *ar)
{
    int err = 0;

    err = msync(ar->addr, ar->len, MS_SYNC);
    if (err) {
        hvfs_err(mdsl, "AIO SYNC region [%p,%ld] failed w/ %d\n",
                 ar->addr, ar->len, errno);
        err = -errno;
    }
    xfree(ar);

    return err;
}

int __serv_sync_unmap_request(struct aio_request *ar)
{
#if 1
    int err = 0;

    err = msync(ar->addr, ar->len, MS_SYNC);
    if (err) {
        hvfs_err(mdsl, "AIO SYNC region [%p,%ld] faield w/ %d\n",
                 ar->addr, ar->len, errno);
        err = -errno;
    }
#elif 1
    int err = 0, i;
    u64 len = ar->len;
    u64 b;

    for (i = 0; len > 0; ) {
        b = min(aio_mgr.sync_len, len);
        err = msync(ar->addr + i, b, MS_SYNC);
        if (err) {
            hvfs_err(mdsl, "AIO SYNC region [%p,%ld] failed w/ %d\n",
                     ar->addr, ar->len, errno);
            err = -errno;
        }
        i += b;
        len -= b;
    }
#else
    err = sync_file_range(ar->fd, ar->foff, ar->len,
                          SYNC_FILE_RANGE_WAIT_BEFORE | SYNC_FILE_RANGE_WRITE);
    if (err) {
        hvfs_err(mdsl, "AIO fadvise region [%lx,%ld] failed w/ %d\n",
                 ar->foff, ar->len, errno);
        err = -errno;
    }
#endif
    atomic64_add(ar->len, &hmo.prof.storage.wbytes);
    madvise(ar->addr, ar->mlen, MADV_DONTNEED);
    err = munmap(ar->addr, ar->mlen);
    if (err) {
        hvfs_err(mdsl, "AIO UNMAP region [%p,%ld] failed w/ %d\n",
                 ar->addr, ar->mlen, errno);
        err = -errno;
    }
    hvfs_debug(mdsl, "ASYNC FLUSH addr %p, done.\n", ar->addr);
    xfree(ar);

    return err;
}

int __serv_odirect_request(struct aio_request *ar)
{
    int err = 0, bw;
    u64 len = DISK_SEC_ROUND_UP(ar->len);

    /* this is a sync operation, the bw is always equals to ar->len! */
    
    bw = pwrite(ar->fd, ar->addr, len, ar->foff);
    if (bw < 0) {
        hvfs_err(mdsl, "pwrite odirect fd %d failed w/ %d[len %ld, foff %lx]\n", 
                 ar->fd, errno, len, ar->foff);
        err = -errno;
        goto out;
    }
    if (bw < len) {
        hvfs_err(mdsl, "Should we support O_DIRECT redo?\n");
    }
    /* we should release the buffer now */
    xfree(ar->addr);
    xfree(ar);
out:            
    return err;
}

static inline
int __serv_request(void)
{
    struct aio_request *ar = NULL, *pos, *n;
    int err = 0;
    
    xlock_lock(&aio_mgr.qlock);
    list_for_each_entry_safe(pos, n, &aio_mgr.queue, list) {
        list_del_init(&pos->list);
        ar = pos;
        break;
    }
    xlock_unlock(&aio_mgr.qlock);

    if (!ar)
        return -EHSTOP;

    /* ok ,deal with it */
    atomic64_inc(&hmo.prof.storage.aio_handled);
    switch (ar->type) {
    case MDSL_AIO_SYNC:
        err = __serv_sync_request(ar);
        if (err) {
            hvfs_err(mdsl, "Handle AIO SYNC request failed w/ %d\n", err);
        }
        break;
    case MDSL_AIO_SYNC_UNMAP:
        err = __serv_sync_unmap_request(ar);
        if (err) {
            hvfs_err(mdsl, "Handle AIO SYNC UNMAP request faield w/ %d\n", err);
        }
        break;
    case MDSL_AIO_ODIRECT:
        err = __serv_odirect_request(ar);
        if (err) {
            hvfs_err(mdsl, "Handle AIO odirect request failed w/ %d\n", err);
        }
        break;
    default:
        hvfs_err(mdsl, "Invalid aio_request type %x\n", ar->type);
    }

    __mdsl_aio_qdcheck(MDSL_AIO_QDCHECK_UNLOCK);
    return err;
}

static
void *aio_main(void *arg)
{
    struct aio_thread_arg *ata = (struct aio_thread_arg *)arg;
    sigset_t set;
    int err = 0;

    /* first, let us block the SIGALRM and SIGCHLD */
    sigemptyset(&set);
    sigaddset(&set, SIGALRM);
    sigaddset(&set, SIGCHLD);
    pthread_sigmask(SIG_BLOCK, &set, NULL); /* oh, we do not care about the
                                             * errs */
    while (!hmo.aio_thread_stop) {
        err = sem_wait(&aio_mgr.qsem);
        if (err == EINTR)
            continue;
        hvfs_debug(mdsl, "AIO thread %d wakeup to handle the requests.\n",
                   ata->tid);
        /* trying to handle more and more IOs */
        while (1) {
            err = __serv_request();
            if (err == -EHSTOP)
                break;
            else if (err) {
                hvfs_err(mdsl, "AIO thread handle request w/ error %d\n",
                         err);
            }
        }
    }
    pthread_exit(0);
}


int mdsl_aio_create(void)
{
    struct aio_thread_arg *ata;
    int i, err = 0;

    /* init the mgr struct  */
    INIT_LIST_HEAD(&aio_mgr.queue);
    xlock_init(&aio_mgr.qlock);
    sem_init(&aio_mgr.qsem, 0, 0);
    sem_init(&aio_mgr.qdsem, 0, MDSL_AIO_MAX_QDEPTH);
    aio_mgr.pending_writes = 0;

    if (!hmo.conf.aio_sync_len) {
        hmo.conf.aio_sync_len = MDSL_AIO_SYNC_SIZE_DEFAULT;
        aio_mgr.sync_len = MDSL_AIO_SYNC_SIZE_DEFAULT;
    }

    /* init aio threads' pool */
    if (!hmo.conf.aio_threads)
        hmo.conf.aio_threads = 8;

    hmo.aio_thread = xzalloc(hmo.conf.aio_threads * sizeof(pthread_t));
    if (!hmo.aio_thread) {
        hvfs_err(mdsl, "xzalloc() pthread_t failed\n");
        return -ENOMEM;
    }

    ata = xzalloc(hmo.conf.aio_threads * sizeof(struct aio_thread_arg));
    if (!ata) {
        hvfs_err(mdsl, "xzalloc() struct aio_thread_arg failed\n");
        err = -ENOMEM;
        goto out_free;
    }

    for (i = 0; i < hmo.conf.aio_threads; i++) {
        (ata + i)->tid = i;
        err = pthread_create(hmo.aio_thread + i, NULL, &aio_main,
                             ata + i);
        if (err)
            goto out;
    }

out:
    return err;
out_free:
    xfree(hmo.aio_thread);
    goto out;
}

void mdsl_aio_destroy(void)
{
    int i;

    hmo.aio_thread_stop = 1;
    for (i = 0; i < hmo.conf.aio_threads; i++) {
        sem_post(&aio_mgr.qsem);
    }
    for (i = 0; i < hmo.conf.aio_threads; i++) {
        pthread_join(*(hmo.aio_thread + i), NULL);
    }
    sem_destroy(&aio_mgr.qsem);
}