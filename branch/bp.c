/**
 * Copyright (c) 2009 Ma Can <ml.macana@gmail.com>
 *                           <macan@ncic.ac.cn>
 *
 * Armed with EMACS.
 * Time-stamp: <2010-12-12 01:43:13 macan>
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

#include "branch.h"

/* Branch Processor is a line processing framework, which feeds the input
 * lines through a list of operators. Operators can be predefined analysis
 * functions, foreign indexers, loggers, or other tools which implemented the
 * callback function.
 */

int bac_init(struct branch_operator *bo, int hsize)
{
    int err = 0, i;
    
    hsize = (hsize == 0) ? BAC_DEFAULT_SIZE : hsize;
    bo->bac.ht = xzalloc(hsize * sizeof(struct regular_hash));
    if (!bo->bac.ht) {
        hvfs_err(xnet, "BAC (ack cache) hash table allocation "
                 "failed\n");
        err = -ENOMEM;
        goto out;
    }
    for (i = 0; i < hsize; i++) {
        INIT_HLIST_HEAD(&bo->bac.ht[i].h);
        xlock_init(&bo->bac.ht[i].lock);
    }
    bo->bac.hsize = hsize;
    atomic_set(&bo->bac.asize, 0);
    
out:
    return err;
}

void bac_destroy(struct branch_operator *bo)
{
    xfree(bo->bac.ht);
}

static inline 
u32 __bac_hash(u64 key, struct branch_ack_cache *bac)
{
    return RSHash((char *)(&key), sizeof(u64)) % bac->hsize;
}

int bac_insert(struct branch_ack_cache_entry *bace,
               struct branch_ack_cache *bac)
{
    struct regular_hash *rh;
    struct branch_ack_cache_entry *tpos;
    struct hlist_node *pos;
    int i;
    
    i = __bac_hash(bace->bacd.site_id, bac);
    rh = bac->ht + i;

    i = 0;
    xlock_lock(&rh->lock);
    hlist_for_each_entry(tpos, pos, &rh->h, hlist) {
        if (bace->bacd.site_id == tpos->bacd.site_id) {
            i = 1;
            break;
        }
    }
    if (!i)
        hlist_add_head(&bace->hlist, &rh->h);
    xlock_unlock(&rh->lock);

    if (i) {
        return -EEXIST;
    }
    atomic_inc(&bac->asize);

    return 0;
}

struct branch_ack_cache_entry *bac_remove(u64 site_id,
                                          struct branch_ack_cache *bac)
{
    struct regular_hash *rh;
    struct branch_ack_cache_entry *tpos;
    struct hlist_node *pos, *n;
    int i;

    i = __bac_hash(site_id, bac);
    rh = bac->ht + i;

    i = 0;
    xlock_lock(&rh->lock);
    hlist_for_each_entry_safe(tpos, pos, n, &rh->h, hlist) {
        if (site_id == tpos->bacd.site_id) {
            hlist_del(&tpos->hlist);
            atomic_dec(&bac->asize);
            xlock_lock(&rh->lock);
            return tpos;
        }
    }
    xlock_lock(&rh->lock);

    return ERR_PTR(-ENOTEXIST);
}

int bac_update(u64 site_id, u64 ack, struct branch_ack_cache *bac)
{
    struct regular_hash *rh;
    struct branch_ack_cache_entry *tpos;
    struct hlist_node *pos;
    int i, err = 0;

    i = __bac_hash(site_id, bac);
    rh = bac->ht + i;

retry:
    i = 0;
    xlock_lock(&rh->lock);
    hlist_for_each_entry(tpos, pos, &rh->h, hlist) {
        if (site_id == tpos->bacd.site_id) {
            /* FIXME: rewind of ack and id */
            tpos->bacd.last_ack = max(tpos->bacd.last_ack,
                                      ack);
            i = 1;
        }
    }
    xlock_unlock(&rh->lock);

    if (!i) {
        struct branch_ack_cache_entry *bace;

        hvfs_warning(xnet, "WARNING: this should not happen: "
                     "update is always after lookup, cache entry "
                     "is missing?\n");

        bace = xzalloc(sizeof(*bace));
        if (!bace) {
            hvfs_err(xnet, "xzalloc() ack cache entry failed\n");
            err = -ENOMEM;
            goto out;
        }
        INIT_HLIST_NODE(&bace->hlist);
        bace->bacd.site_id = site_id;
        bace->bacd.last_ack = ack;
        if (ack != 0)
            hvfs_err(xnet, "create ack entry %ld which "
                     "largger than 0\n",
                     ack);
        err = bac_insert(bace, bac);
        if (err) {
            hvfs_err(xnet, "insert ack cache entry %lx "
                     "failed w/ %d\n",
                     site_id, err);
            xfree(bace);
            goto out;
        }
        goto retry;
    }

out:
    return err;
}

int bac_lookup_create(u64 site_id, u64 ack, u64 id, 
                      struct branch_ack_cache *bac)
{
    struct regular_hash *rh;
    struct branch_ack_cache_entry *tpos;
    struct hlist_node *pos;
    int i, err = 0;

    i = __bac_hash(site_id, bac);
    rh = bac->ht + i;

retry:
    i = 0;
    xlock_lock(&rh->lock);
    hlist_for_each_entry(tpos, pos, &rh->h, hlist) {
        if (site_id == tpos->bacd.site_id) {
            /* follow the ruls noted at 12/4/2010. please refer to the
             * notebook. */
            /* FIXME: rewind of ack and id */
            if (ack == 0) {
                hvfs_warning(xnet, "detect BE restarting, "
                             "reset BE.last_ack to %ld\n",
                             tpos->bacd.last_ack + 1);
                err = -EADJUST;
            } else if (ack == tpos->bacd.last_ack) {
                if (id <= tpos->bacd.last_ack) {
                    err = -EIGNORE;
                }
            } else if (ack < tpos->bacd.last_ack) {
                if (id <= tpos->bacd.last_ack) {
                    err = -EADJUST;
                } else {
                    /* FIXME: if there is a ACk recievied by the original
                     * site, the ack handler should resend this branch line
                     * immedidately */
                    err = -EHWAIT;
                }
            } else {
                /* ack > bp.last_ack */
                hvfs_warning(xnet, "detect BP restarting, "
                             "reset BP.last_ack to %ld\n",
                             ack);
                tpos->bacd.last_ack = ack;
            }
            i = 1;
        }
    }
    xlock_unlock(&rh->lock);

    if (!i) {
        /* we should create a new branch ack cache entry */
        struct branch_ack_cache_entry *bace;
        
        bace = xzalloc(sizeof(*bace));
        if (!bace) {
            hvfs_err(xnet, "xzalloc() ack cache entry failed\n");
            err = -ENOMEM;
            goto out;
        }
        INIT_HLIST_NODE(&bace->hlist);
        bace->bacd.site_id = site_id;
        bace->bacd.last_ack = ack;
        if (ack != 0)
            hvfs_err(xnet, "create ack entry %ld which "
                     "largger than 0\n",
                     ack);
        err = bac_insert(bace, bac);
        if (err) {
            hvfs_err(xnet, "insert ack cache entry %lx "
                     "failed w/ %d\n",
                     site_id, err);
            xfree(bace);
            goto out;
        }
        goto retry;
    }

out:
    return err;
}

/* bac_load() should be called ONCE at the init phase.
 */
int bac_load(struct branch_operator *bo, 
             struct branch_ack_cache_disk *bacd, int nr)
{
    struct branch_ack_cache_entry *bace;
    int err = 0, i;
    
    /* update the hash table now */
    for (i = 0; i < nr; i++) {
        bace = xzalloc(sizeof(*bace));
        if (!bace) {
            hvfs_err(xnet, "xzalloc() ack cache entry failed\n");
            err = -ENOMEM;
            goto out_clean;
        }
        INIT_HLIST_NODE(&bace->hlist);
        bace->bacd = *(bacd + i);

        /* insert to the hash table */
        err = bac_insert(bace, &bo->bac);
        if (err) {
            hvfs_err(xnet, "insert ack cache entry %lx "
                     "failed w/ %d\n",
                     (bacd + i)->site_id, err);
            xfree(bace);
            goto out_clean;
        }
    }

    return 0;
out_clean:
    for (i--; i >= 0; i--) {
        bace = bac_remove((bacd + i)->site_id, &bo->bac);
        if (IS_ERR(bace)) {
            hvfs_err(xnet, "lookup ack cache entry %lx "
                     "failed w/ %ld\n",
                     (bacd + i)->site_id, PTR_ERR(bace));
        } else 
            xfree(bace);
    }

    return err;
}

/* flush the branch ack cache to a buffer */
int bac_flush(struct branch_ack_cache *bac, void **data, size_t *len)
{
    struct branch_ack_cache_disk *bacd;
    struct regular_hash *rh;
    struct branch_ack_cache_entry *tpos;
    struct hlist_node *pos;
    int i, j;

    /* we are sure that there is no other operation access this cache. all the
     * accesses to this cache is sequential with out ANY race. */
    *len = atomic_read(&bac->asize) * 
        sizeof(struct branch_ack_cache_disk);

    bacd = xmalloc(*len);
    if (!bacd) {
        hvfs_err(xnet, "xmalloc() result buffer for bac failed\n");
        return -ENOMEM;
    }
    
    for (i = 0, j = 0; i < bac->hsize; i++) {
        rh = bac->ht + i;
        xlock_lock(&rh->lock);
        hlist_for_each_entry(tpos, pos, &rh->h, hlist) {
            /* copy this entry to the result buffer */
            *(bacd + j) = tpos->bacd;
            j++;
        }
        xlock_unlock(&rh->lock);
    }
    ASSERT(j * sizeof(*bacd) <= *len, xnet);

    *data = bacd;

    return 0;
}

/* branch operator functions
 */
struct branch_operator *bo_alloc(void)
{
    struct branch_operator *bo;

    bo = xzalloc(sizeof(*bo));
    if (!bo) {
        hvfs_err(xnet, "alloc branch operator failed\n");
        return NULL;
    }

    INIT_LIST_HEAD(&bo->list);
    
    return bo;
}

void bo_free(struct branch_operator *bo)
{
    xfree(bo);
}

int bo_init(struct branch_operator *bo, struct branch_op_result *bor,
            struct branch_op *bop, char *name,
            struct branch_operator *left,
            struct branch_operator *right)
{
    int err = 0;
    
    /* Step 0: setup the callback functions */
    err = __bo_install_cb(bo, name);
    if (err) {
        hvfs_err(xnet, "BO install '%s' callback functions "
                 "failed w/ %d\n",
                 name, err);
        goto out;
    }

    /* Step 1: preprocessing the branch_op_result by call the open callback
     * function */
    if (bor && bo->open) {
        err = bo->open(bo, bor, bop);
        if (err) {
            hvfs_err(xnet, "callback BO->open() failed w/ %d\n",
                     err);
            goto out;
        }
    }
    
    /* Step 2: init the other fileds in bo */
    bo->left = left;
    bo->right = right;
    /* we do not duplicate the name string */
    bo->name = name;

    /* Step 3: init the ack cache now */
    err = bac_init(bo, 0);
    if (err) {
        hvfs_err(xnet, "init branch ack cache failed w/ %d\n",
                 err);
        goto out;
    }

out:
    return err;
}

void bo_destroy(struct branch_operator *bo)
{
    /* close the left and right subtree */
    if (bo->left)
        bo_destroy(bo->left);
    if (bo->right)
        bo_destroy(bo->right);
    
    if (bo->close) {
        bo->close(bo);
    }
    bac_destroy(bo);
}

int bo_root_flush(struct branch_processor *bp,
                  struct branch_operator *bo, void **oresult,
                  size_t *osize)
{
    struct branch_entry *be;
    void *data;
    size_t len = 0;
    int err = 0;

    /* Step 1: get the branch ack cache content */
    err = bac_flush(&bo->bac, &data, &len);
    if (err) {
        hvfs_err(xnet, "branch ack cache flush failed w/ %d\n",
                 err);
        goto out;
    }

    /* Step 2: write to the branch file column 1 */
    be = bp->be;
    {
        struct hstat hs;
        struct mdu_update *mu = NULL;
        u64 buuid, bsalt;

        /* find the root branch dir */
        memset(&hs, 0, sizeof(hs));
        hs.name = ".branches";
        hs.puuid = hmi.root_uuid;
        hs.psalt = hmi.root_salt;

        err = hvfs_stat_eh(hmi.root_uuid, hmi.root_salt, -1, &hs);
        if (err) {
            hvfs_err(xnet, "Root branch does not exist, w/ %d\n",
                     err);
            goto out_free;
        }
        hs.hash = 0;
        err = hvfs_stat_eh(hmi.gdt_uuid, hmi.gdt_salt, -1, &hs);
        if (err) {
            hvfs_err(xnet, "do internal dir stat (GDT) on root branch "
                     "failed w/ %d\n", err);
            goto out_free;
        }

        /* find the branch now */
        buuid = hs.uuid;
        bsalt = hs.ssalt;
        memset(&hs, 0, sizeof(hs));
        hs.puuid = buuid;
        hs.psalt = bsalt;
        hs.name = be->branch_name;
        err = hvfs_stat_eh(buuid, bsalt, -1, &hs);
        if (err) {
            hvfs_err(xnet, "do internal file stat (SDT) on branch '%s'"
                     " failed w/ %d\n",
                     be->branch_name, err);
            goto out_free;
        }

        /* write the ack cache entry to column[1] */
        err = hvfs_fwrite_eh(&hs, 1, 0, data, len, &hs.mc.c);
        if (err) {
            hvfs_err(xnet, "write the branch '%s' c[1] failed w/ %d\n",
                     be->branch_name, err);
            goto out_free;
        }
        /* update the metadata */
        mu = xzalloc(sizeof(*mu));
        if (!mu) {
            hvfs_err(xnet, "alloc mdu_update failed\n");
            err = -ENOMEM;
            goto out_free;
        }
        mu->valid = MU_COLUMN;
        mu->column_no = 1;
        hs.mc.cno = 1;          /* make sure we update column[1] */
        
        hs.name = NULL;
        /* access SDT, using the old hs.hash value */
        err = hvfs_update_eh(buuid, bsalt, &hs, mu);
        if (err) {
            hvfs_err(xnet, "do internal update on '%s' failed w/ %d\n",
                     be->branch_name, err);
            goto out_free2;
        }
    out_free2:
        xfree(mu);
    }
    
out_free:
    xfree(data);
out:
    return err;
}

/* @site: this site should be the original site, not msg->tx.ssite_id!
 */
int bo_root_input(struct branch_processor *bp,
                  struct branch_operator *bo,
                  struct branch_line_disk *bld, 
                  u64 site, u64 ack, int *errstate)
{
    int err = 0;
    
    /* check if it is a flush operation */
    if (*errstate == BO_FLUSH) {
        if (bo->flush)
            err = bo->flush(bp, bo, NULL, NULL);
        else
            err = -EINVAL;
        
        if (err) {
            hvfs_err(xnet, "flush ack cache of operator %s failed"
                     " w/ %d\n", bo->name, err);
            *errstate = BO_STOP;
            return -EHSTOP;
        }
    } else if (*errstate == BO_STOP) {
        return -EHSTOP;
    }
    
    /* for root operator, reset the errstate to OK */
    *errstate = 0;

    /* sanity check */
    if (!bp || !bld) {
        *errstate = BO_STOP;
        return -EINVAL;
    }
    /* check the ack cache */
    err = bac_lookup_create(site, ack, bld->bl.id, &bo->bac);
    if (err) {
        /* this means we can't deal with this bld */
        *errstate = BO_STOP;
        goto out;
    }
    
    /* deal with data now, actually do nothing */
    err = 0;
    
out:
    return err;
}

/* output function deal with the input branch line and transform the input
 * to new format. For root operator, do not change the input */

/* filter_open() to load in the metadata for filter rules and output file
 *
 * API: (string in branch_op->data)
 * 1. rule:regular_expression_list
 * 2. output:/path/to/name
 *
 * regular_expression_list: regex1;regex2;regex3;
 *
 * Note that: all the regexes are AND connected! But, at this moment, we just
 * support ONE regex!
 */
int bo_filter_open(struct branch_operator *bo,
                   struct branch_op_result *bor,
                   struct branch_op *op)
{
    /* Note that, filter operation do not save anything in the global branch
     * result file (c[2]). All the filtered lines are saved in the dedicated
     * output file specified by user. Thus, for this open function, we must
     * get the metadata from branch_op structure */
    struct bo_filter *bf;
    char *regex = "rule:([^;]*);+;output_filename:([^;]*);*";
    char *p, *sp;
    int err = 0;

    /* Step 1: parse the arguments from branch op */
    if (!op || !op->data) {
        return -EINVAL;
    }

    bf = xzalloc(sizeof(*bf));
    if (!bf) {
        hvfs_err(xnet, "xzalloc() bo_filter failed\n");
        return -ENOMEM;
    }

    bf->buffer = xzalloc(BO_FILTER_CHUNK);
    if (!bf->buffer) {
        hvfs_err(xnet, "xzalloc() bo_filter buffer failed\n");
        xfree(bf);
        return -ENOMEM;
    }
    bf->size = BO_FILTER_CHUNK;
    
    p = op->data;
    p = strtok_r(p, "rule:", &sp);
    if (!p) {
        /* no rule means that we will accept all the input lines */
        bf->accept_all = 1;
        regex = "output_filename:([^;]*);*";
    }
    p = op->data;
    p = strtok_r(p, "output_filename:", &sp);
    if (!p) {
        /* no output file name means we can just ignore this op */
        bf->accept_all = -1;
        regex = NULL;
    }
    
    if (regex) {
        /* parse the regex strings */
        regex_t preg;
        regmatch_t *pmatch;
        char errbuf[op->len + 1];
        int i, len;

        pmatch = xzalloc(3 * sizeof(regmatch_t));
        if (!pmatch) {
            hvfs_err(xnet, "malloc regmatch_t failed\n");
            err = -ENOMEM;
            goto out_free;
        }
        err = regcomp(&preg, regex, REG_EXTENDED);
        if (err) {
            hvfs_err(xnet, "regcomp failed w/ %d\n", err);
            goto out_free2;
        }
        err = regexec(&preg, op->data, 3, pmatch, 0);
        if (err) {
            regerror(err, &preg, errbuf, op->len);
            hvfs_err(xnet, "regexec failed w/ '%s'\n", errbuf);
            goto out_clean;
        }

        for (i = 1; i < 3; i++) {
            if (pmatch[i].rm_so == -1)
                break;
            len = pmatch[i].rm_eo - pmatch[i].rm_so;
            memcpy(errbuf, op->data + pmatch[i].rm_so, len);
            errbuf[len] = '\0';
            if (bf->accept_all == 1 && i == 1) {
                bf->filename = strdup(errbuf);
                break;
            } else {
                if (i == 1) {
                    /* get rule, thus compute the regex_t */
                    err = regcomp(&bf->preg, errbuf, REG_EXTENDED);
                    if (err) {
                        hvfs_err(xnet, "regcomp failed w/ %d\n",
                                 err);
                        goto out_clean;
                    }
                } else {
                    /* output_filename */
                    bf->filename = strdup(errbuf);
                }
            }
        }
    out_clean:
        regfree(&preg);
    out_free2:
        xfree(pmatch);
        if (err)
            goto out_free;
    }

    /* set the bf to gdata */
    bo->gdata = bf;
    
out_free:
    xfree(bf);
    return err;
}

int bo_filter_close(struct branch_operator *bo)
{
    struct bo_filter *bf = bo->gdata;
    
    /* fileter close just release all the internal states */
    if (bf->accept_all == 0)
        regfree(&bf->preg);
    if (bf->accept_all != -1)
        xfree(bf->filename);

    return 0;
}

/* Generate the filtered result buffer to flush. Note that we will write the
 * internal buffer to the output file (of course, in append mode).
 */
int bo_filter_flush(struct branch_processor *bp,
                    struct branch_operator *bo, void **oresult,
                    size_t *osize)
{
    struct bo_filter *bf = (struct bo_filter *)bo->gdata;
    char *path, *name;
    int err = 0;

    if (!bf->size || bf->accept_all == -1)
        return 0;

    /* in bp mode, we are sure that we are not MDS and MDSL. Thus, feel free
     * to call all the api functions. */
    path = dirname(bf->filename);
    name = basename(bf->filename);
    err = hvfs_fwrite(path, name, 0, bf->buffer, bf->offset, SCD_PROXY);
    if (err) {
        hvfs_err(xnet, "flush filter buffer to %s failed w/ %d\n",
                 bf->filename, err);
        goto out;
    }

    /* then, it is ok to clean and reset the buffer now */
    bf->offset = 0;

out:
    return err;
}

int bo_filter_input(struct branch_processor *bp,
                    struct branch_operator *bo,
                    struct branch_line_disk *bld,
                    u64 site, u64 ack, int *errstate)
{
    struct bo_filter *bf;
    int err = 0;

    /* check if it is a flush operation */
    if (*errstate == BO_FLUSH) {
        if (bo->flush)
            err = bo->flush(bp, bo, NULL, NULL);
        else
            err = -EINVAL;

        if (err) {
            hvfs_err(xnet, "flush filter buffer of operator %s "
                     "failed w/ %d\n", bo->name, err);
            *errstate = BO_STOP;
            return -EHSTOP;
        }
    } else if (*errstate == BO_STOP) {
        return -EHSTOP;
    }

    /* sanity check */
    if (!bp || !bld) {
        *errstate = BO_STOP;
        return -EINVAL;
    }

    /* deal with data now */
    bf = (struct bo_filter *)bo->gdata;
    if (bf->accept_all > 0) {
        /* save the input data to the buffer */
    retry:
        if (bf->offset + bld->bl.data_len > bf->size) {
            /* need to realloc the buffer now */
            void *p = xrealloc(bf->buffer, bf->size + BO_FILTER_CHUNK);
            if (!p) {
                hvfs_err(xnet, "realloc buffer space to %d failed\n",
                         bf->size + BO_FILTER_CHUNK);
                *errstate = BO_STOP;
                return -ENOMEM;
            }
            bf->size += BO_FILTER_CHUNK;
            bf->buffer = p;
            goto retry;
        }
        memcpy(bf->buffer + bf->offset, bld->bl.data,
               bld->bl.data_len);
        bf->offset += bld->bl.data_len;
    } else if (bf->accept_all < 0) {
        /* ignore this operator! do not change the OP */
        ;
    } else {
        char string[bld->bl.data_len + 1];

        memcpy(string, bld->bl.data, bld->bl.data_len);
        string[bld->bl.data_len + 1] = '\0';
        err = regexec(&bf->preg, bld->bl.data, 0, NULL, 0);
        if (!err) {
            /* matched, just log current entry and continue */
        retry_again:
            if (bf->offset + bld->bl.data_len > bf->size) {
                /* need to realloc the buffer now */
                void *p = xrealloc(bf->buffer,
                                   bf->size + BO_FILTER_CHUNK);
                if (!p) {
                    hvfs_err(xnet, "realloc buffer space to %d failed\n",
                             bf->size + BO_FILTER_CHUNK);
                    *errstate = BO_STOP;
                    return -ENOMEM;
                }
                bf->size += BO_FILTER_CHUNK;
                bf->buffer = p;
            goto retry_again;
            }
            memcpy(bf->buffer + bf->offset, bld->bl.data,
                   bld->bl.data_len);
            bf->offset += bld->bl.data_len;
        } else if (err == REG_NOMATCH) {
            /* not matched, swallow this entry */
            *errstate = BO_STOP;
            err = 0;
        } else if (err) {
            *errstate = BO_STOP;
            return -EHSTOP;
        }
    }

    return err;
}

struct branch_processor *bp_alloc(void)
{
    struct branch_processor *bp;

    bp = xzalloc(sizeof(*bp));
    if (!bp) {
        hvfs_err(xnet, "alloc branch processor failed\n");
        return NULL;
    }

    INIT_LIST_HEAD(&bp->oplist);
    atomic_set(&bp->bonr, 0);
    bp->bpto = BP_DEFAULT_BTO;
    bp->memlimit = BP_DEFAULT_MEMLIMIT;

    /* init the root operator */
    bo_init(&bp->bo_root, NULL, NULL, "root", NULL, NULL);

    return bp;
}

int __bo_install_cb(struct branch_operator *bo, char *name)
{
    if (strcmp(name, "root") == 0) {
        bo->flush = bo_root_flush;
        bo->input = bo_root_input;
    } else if (strcmp(name, "filter") == 0) {
        bo->open = bo_filter_open;
        bo->close = bo_filter_close;
        bo->input = bo_filter_input;
        bo->flush = bo_filter_flush;
    } else {
        hvfs_err(xnet, "Operator %s is not support yet.\n",
                 name);
        return -ENOSYS;
    }

    return 0;
}

void bp_destroy(struct branch_processor *bp)
{
    struct branch_operator *bo, *n;

    list_for_each_entry_safe(bo, n, &bp->oplist, list) {
        list_del(&bo->list);
        bo_destroy(bo);
    }

    bo_destroy(&bp->bo_root);

    xfree(bp);
}

struct branch_processor *bp_alloc_init(struct branch_entry *be,
                                       struct branch_op_result *bor)
{
    struct branch_processor *bp;
    struct branch_operator *bo;
    int i;

    bp = bp_alloc();
    if (!bp) {
        hvfs_err(xnet, "alloc branch processor failed\n");
        return NULL;
    }

    /* construct the operator list */
    for (i = 0; i < be->bh->ops.nr; i++) {
        bo = bo_alloc();
        if (!bo) {
            hvfs_err(xnet, "bo_alloc() '%s'->op %d failed\n",
                     be->branch_name, be->bh->ops.ops[i].op);
            continue;
        }
        bo->id = be->bh->ops.ops[i].id;

        switch(be->bh->ops.ops[i].op) {
        case BRANCH_OP_FILTER:
            bo_init(bo, bor, &be->bh->ops.ops[i], "filter", NULL, NULL);
            break;
        case BRANCH_OP_SUM:
            bo_init(bo, bor, &be->bh->ops.ops[i], "sum", NULL, NULL);
            break;
        case BRANCH_OP_MAX:
            bo_init(bo, bor, &be->bh->ops.ops[i], "max", NULL, NULL);
            break;
        case BRANCH_OP_MIN:
            bo_init(bo, bor, &be->bh->ops.ops[i], "min", NULL, NULL);
            break;
        case BRANCH_OP_TOPN:
            bo_init(bo, bor, &be->bh->ops.ops[i], "topn", NULL, NULL);
            break;
        case BRANCH_OP_GROUPBY:
            bo_init(bo, bor, &be->bh->ops.ops[i], "groupby", NULL, NULL);
            break;
        case BRANCH_OP_RANK:
            bo_init(bo, bor, &be->bh->ops.ops[i], "rank", NULL, NULL);
            break;
        case BRANCH_OP_INDEXER:
            bo_init(bo, bor, &be->bh->ops.ops[i], "indexer", NULL, NULL);
            break;
        case BRANCH_OP_CODEC:
            bo_init(bo, bor, &be->bh->ops.ops[i], "udf_codec", NULL, NULL);
            break;
        default:
            hvfs_err(xnet, "Invalid operator %d\n",
                     be->bh->ops.ops[i].op);
            bo_free(bo);
            continue;
        }

        /* add this operator to the bp oplist */
        xlock_lock(&bp->lock);
        list_add_tail(&bo->list, &bp->oplist);
        atomic_inc(&bp->bonr);
        xlock_unlock(&bp->lock);
    }

    return bp;
}

int __bp_handle_push_console(struct xnet_msg *msg, 
                             struct branch_line_disk *bld)
{
    u64 site;
    int err = 0;

    if (bld->bl.position == BL_PRIMARY) {
        site = msg->tx.ssite_id;
    } else if (bld->bl.position == BL_REPLICA) {
        site = bld->bl.sites[0];
    } else {
        hvfs_err(xnet, "Invalid branch line postion %d\n",
                 bld->bl.position);
        return -EINVAL;
    }

    hvfs_info(xnet, "BL pushed from %lx Psite %lx id %ld last_ack %ld\n",
              msg->tx.ssite_id, site, bld->bl.id, msg->tx.arg1);
    
    return err;
}

int bp_handle_push(struct branch_processor *bp, struct xnet_msg *msg,
                   struct branch_line_disk *bld)
{
    u64 site, ack;
    int errstate = 0, err = 0;
    
    if (!bp)
        return __bp_handle_push_console(msg, bld);

    /* setup the bld structure */
    bld->bl.data = bld->data + bld->name_len + bld->tag_len;
    ack = msg->tx.arg1;
    if (bld->bl.position == BL_PRIMARY) {
        site = msg->tx.ssite_id;
    } else if (bld->bl.position == BL_REPLICA) {
        site = bld->bl.sites[0];
    } else {
        hvfs_err(xnet, "Invalid branch line postion %d\n",
                 bld->bl.position);
        return -EINVAL;
    }

    /* calling the processor framework and begin processing */

    /* Step 1: push the branch line to root operator */
    err = bp->bo_root.input(bp, &bp->bo_root, bld, site, ack,
                            &errstate);
    if (errstate == BO_STOP) {
        if (err) {
            hvfs_err(xnet, "root operator failed w/ %d "
                     "(Pste %lx from %lx id %ld, last_ack %ld)\n",
                     err, site, msg->tx.ssite_id, bld->bl.id, ack);
        } else {
            hvfs_err(xnet, "root operator swallow this branch "
                     "line (Psite %lx from %lx id %ld, "
                     "last_ack %ld)\n",
                     site, msg->tx.ssite_id, bld->bl.id, ack);
        }
        goto out;
    }

    /* Step 2: push the branch line to other operatores */

out:
    return err;
}