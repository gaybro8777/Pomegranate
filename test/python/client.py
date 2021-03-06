#!/bin/env python
#
# Copyright (c) 2009 Ma Can <ml.macana@gmail.com>
#                           <macan@ncic.ac.cn>
#
# Time-stamp: <2013-02-19 14:37:59 macan>
#
# Armed with EMACS.
#
# This file provides a file system client in Python

import os, time, sys
import getopt
import signal
import cmd
import shlex
from ctypes import *

# definations for site
HVFS_SITE_TYPE_CLIENT = 0x01
HVFS_SITE_TYPE_MDS = 0x02
HVFS_SITE_TYPE_MDSL = 0x03
HVFS_SITE_TYPE_R2 = 0x04
HVFS_SITE_TYPE_OSD = 0x05
HVFS_SITE_TYPE_AMC = 0x06
HVFS_SITE_TYPE_BP = 0x07

HVFS_SITE_TYPE_MASK = (0x7 << 17)
HVFS_SITE_MAX = (1 << 20)
HVFS_SITE_N_MASK = ((1 << 17) - 1)

def HVFS_MDS(n):
    return (HVFS_SITE_TYPE_MDS << 17) | (int(n) & HVFS_SITE_N_MASK)

def HVFS_OSD(n):
    return (HVFS_SITE_TYPE_OSD << 17) | (int(n) & HVFS_SITE_N_MASK)

try:
    libc = CDLL("libc.so.6")
    lib = CDLL("../../lib/libhvfs.so.1.0", mode=RTLD_GLOBAL)
    xnet = CDLL("../../lib/libxnet.so.1.0", mode=RTLD_GLOBAL)
    mds = CDLL("../../lib/libmds.so.1.0", mode=RTLD_GLOBAL)
    root = CDLL("../../lib/libr2.so.1.0", mode=RTLD_GLOBAL)
    api = CDLL("../../lib/libapi.so.1.0", mode=RTLD_GLOBAL)
    branch = CDLL("../../lib/libbranch.so.1.0", mode=RTLD_GLOBAL)
except OSError, oe:
    print "Can not load shared library: %s" % oe
    sys.exit()

def errcheck(res, func, args):
    if not res: raise IOError
    return res

class bcolors:
    HEADER = '\033[36m'
    OKPINK = '\033[35m'
    OKBLUE = '\033[34m'
    OKGREEN = '\033[32m'
    WARNING = '\033[33m'
    FAIL = '\033[41m'
    ENDC = '\033[0m'
    mode = True

    def flip(self):
        if self.mode == True:
            self.mode = False
        else:
            self.mode = True

    def print_warn(self, string):
        if self.mode:
            print bcolors.WARNING + str(string) + bcolors.ENDC
        else:
            print str(string)

    def print_err(self, string):
        if self.mode:
            print bcolors.FAIL + str(string) + bcolors.ENDC
        else:
            print str(string)

    def print_ok(self, string):
        if self.mode:
            print bcolors.OKGREEN + str(string) + bcolors.ENDC
        else:
            print str(string)

    def print_pink(self, string):
        if self.mode:
            print bcolors.OKPINK + str(string) + bcolors.ENDC
        else:
            print str(string)

class struct_hmo(Structure):
    '''struct_hmo is a shadow structure of hvfs_mds_object.
    thus, if you change hvfs_mds_object, you must change 'others' offset'''
    _fields_ = [("others", c_char * 1984),
                ("branch_dispatch", c_void_p),
                ("cb_exit", c_void_p),
                ("cb_hb", c_void_p),
                ("cb_ring_update", c_void_p),
                ("cb_addr_table_update", c_void_p),
                ("cb_branch_init", c_void_p),
                ("cb_branch_destroy", c_void_p),
                ]

class struct_branch_op(Structure):
    FILTER = 0x0001
    SUM = 0x0002
    MAX = 0x0003
    MIN = 0x0004
    KNN = 0x0005
    GROUPBY = 0x0006
    RANK = 0x0007
    INDEXER = 0x0008
    COUNT = 0x0009
    AVG = 0x000a
    CODEC = 0x0100
    _fields_ = [("op", c_uint32),
                ("len", c_uint32),
                ("id", c_uint32),
                ("rid", c_uint32),
                ("lor", c_uint32),
                ("data", c_void_p),
                ]

class struct_branch_ops(Structure):
    _fields_ = [("nr", c_uint32),
                ("ops", struct_branch_op * 10),
                ]

def client_cb_branch_destroy():
    '''callback function for branch destroy'''
    branch.branch_destroy()

def main(argv):
    try:
        opts, args = getopt.getopt(argv, "ht:i:r:b",
                                   ["help", "thread=", "id=", 
                                    "ring=", "use_branch"])
    except getopt.GetoptError:
        sys.exit()

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    thread = 1
    id = 0
    fsid = 0
    port = 8412
    ring = "127.0.0.1"
    use_branch = False

    try:
        for opt, arg in opts:
            if opt in ("-h", "--help"):
                print_help()
                sys.exit()
            elif opt in ("-t", "--thread"):
                thread = int(arg)
            elif opt in ("-i", "--id"):
                id = int(arg)
            elif opt in ("-r", "--ring"):
                ring = arg
            elif opt in ("-b", "--use_branch"):
                use_branch = True
    except ValueError, ve:
        print "Value error: %s" % ve
        sys.exit()

    print "FS Client %d Running w/ (%d threads)..." % (id, thread)

    # init the FS client
    CSTR_ARRAY = c_char_p * 12
    argv = CSTR_ARRAY("pyAMC", "-d", str(id), "-r", ring, "-p", 
                      str(port + id), "-f", str(fsid), 
                      "-y", "client", '-b')
    err = api.__core_main(12, argv)
    if err != 0:
        print "api.__core_main() failed w/ %d" % err
        return
    if use_branch:
        print bcolors.OKGREEN + "Enable branch feeder mode" + bcolors.ENDC
        err = branch.branch_init(c_int(0), c_int(0), c_uint64(0), 
                                 c_void_p(None))
        if err != 0:
            print "branch.branch_init() failed w/ %d" % err
            return
        hmo = struct_hmo.in_dll(mds, "hmo")
        # The following line is fully of magic :)
        hmo.branch_dispatch = cast(branch.branch_dispatch_split, 
                                   c_void_p).value
        hmo.cb_branch_destroy = cast(CFUNCTYPE(None)
                                     (client_cb_branch_destroy), 
                                     c_void_p).value

    pamc_shell(use_branch).cmdloop("Welcome to Python FS Client Shell, " + 
                                   "for help please input ? or help")

    api.__core_exit(None)

class pamc_shell(cmd.Cmd):
    bc = None
    table = None
    clock_start = 0.0
    clock_stop = 0.0
    use_branch = False
    keywords = ["EOF", "touch", "delete", "stat", "mkdir",
                "rmdir", "cpin", "cpout", "online", "offline",
                "quit", "ls", "commit", "getcluster", "cat", 
                "regdtrigger", "catdtrigger", "statfs", "setattr",
                "getactivesite", "addsite", "rmvsite", "shutdown",
                "cbranch", "bc", "bp", "getbor", "search", 
                "pst", "clrdtrigger", "getinfo", "analysestorage",
                "getactivesitesize", "queryobj"]

    def __init__(self, ub = False):
        cmd.Cmd.__init__(self)
        # Issue reported by Nikhil Agrawal. On machines without readline
        # module, use_rawinput should be True either.
        cmd.Cmd.use_rawinput = True
        self.bc = bcolors()
        self.use_branch = ub

    def emptyline(self):
        return

    def start_clock(self):
        self.clock_start = time.time()
        return

    def stop_clock(self):
        self.clock_stop = time.time()

    def echo_clock(self, str):
        if self.bc.mode:
            print self.bc.OKGREEN + "%s %fs" % (str, 
                                                self.clock_stop 
                                                - self.clock_start) + self.bc.ENDC
        else:
            print "%s %fs" % (str, self.clock_stop - self.clock_start)
        return

    def do_touch(self, line):
        '''Touch a new file in current pathname. If the dirs 
        are not exist, we do NOT create it automatically. Use mkdir itestad.
        Usage: touch path/to/name'''
        l = shlex.split(line)
        if len(l) < 1:
            print "Invalid argument. See help touch."
            return

        l[0] = os.path.normpath(l[0])
        path, file = os.path.split(l[0])
        if path == "" or path[0] != '/':
            print "Relative path name is not supported yet."
            return

        # ok, call api.create to create the file, no recurisive
        try:
            c_path = c_char_p(path)
            c_file = c_char_p(file)
            c_data = c_void_p(None)
            self.start_clock()
            err = api.hvfs_create(c_path, c_file, byref(c_data), 0)
            if err != 0:
                print "api.hvfs_create() failed w/ %d" % err
                return
            self.stop_clock()
            c_str = c_char_p(c_data.value)
            print c_str.value
            self.echo_clock("Time elasped:")
            # free the region
            api.hvfs_free(c_data)
        except ValueError, ve:
            print "ValueError %s" % ve

    def do_mkdir(self, line):
        '''Make a new dir in current pathname.
        Usage: mkdir /path/to/dir'''
        l = shlex.split(line)
        if len(l) < 1:
            print "Invalid argument. See help mkdir."
            return

        l[0] = os.path.normpath(l[0])
        path, file = os.path.split(l[0])
        if path == "" or path[0] != '/':
            print "Relative path name is not supported yet."
            return

        # ok, call api.create to create the dir
        try:
            c_path = c_char_p(path)
            c_file = c_char_p(file)
            c_data = c_void_p(None)
            self.start_clock()
            err = api.hvfs_create(c_path, c_file, byref(c_data), 1)
            if err != 0:
                print "api.hvfs_create() failed w/ %d" % err
                return
            self.stop_clock()
            c_str = c_char_p(c_data.value)
            print c_str.value
            self.echo_clock("Time elasped:")
            # free the region
            api.hvfs_free(c_data)
        except ValueError, ve:
            print "ValueError %s" % ve

    def do_delete(self, line):
        '''Delete a file. If any of the dir does not exist,
        we just reject the operation.
        Usage: delete path/to/name'''
        l = shlex.split(line)
        if len(l) < 1:
            print "Invalid argument. See help delete."
            return
        l[0] = os.path.normpath(l[0])
        path, file = os.path.split(l[0])
        if path == "" or path[0] != '/':
            print "Relative path name is not supported yet."
            return

        # ok, call api.delete to delete the file
        try:
            c_path = c_char_p(path)
            c_file = c_char_p(file)
            c_data = c_void_p(None)
            self.start_clock()
            err = api.hvfs_fdel(c_path, c_file, byref(c_data), 0)
            if err != 0:
                print "api.hvfs_fdel() failed w/ %d" % err
                return
            self.stop_clock()
            c_str = c_char_p(c_data.value)
            print c_str.value
            self.echo_clock("Time elasped:")
            # free the region
            api.hvfs_free(c_data)
        except ValueError, ve:
            print "ValueError %s" % ve

    def do_rmdir(self, line):
        '''Remove a directory by current path name.
        Usage: rmdir /path/to/dir'''
        l = shlex.split(line)
        if len(l) < 1:
            print "Invalid argument. See help rmdir."
            return

        l[0] = os.path.normpath(l[0])
        path, file = os.path.split(l[0])
        if path == "" or path[0] != '/':
            print "Relative path name is not supported yet."
            return

        # ok, call api.delete to delete the directory
        try:
            c_path = c_char_p(path)
            c_file = c_char_p(file)
            c_data = c_void_p(None)
            err = api.hvfs_readdir(c_path, c_file, byref(c_data))
            if err != 0:
                print "api.hvfs_readdir() failed w/ %d" % err
                return
            if c_data.value != None:
                print "Directory '%s/%s' is not empty!" % (path,
                                                           file)
                return
            c_data = c_void_p(None)
            self.start_clock()
            err = api.hvfs_fdel(c_path, c_file, byref(c_data), 1)
            if err != 0:
                print "api.hvfs_fdel() failed w/ %d" % err
                return
            self.stop_clock()
            c_str = c_char_p(c_data.value)
            print c_str.value
            self.echo_clock("Time elasped:")
            # free the region
            api.hvfs_free(c_data)
        except ValueError, ve:
            print "ValueError %s" % ve

    def do_ls(self, line):
        '''List a directory.
        Usage: list /path/to/dir'''
        l = shlex.split(line)
        if len(l) < 1:
            print "Invalid argument. See help ls."
            return

        l[0] = os.path.normpath(l[0])
        path, file = os.path.split(l[0])
        if path == "" or path[0] != '/':
            print "Relative path name is not support yet."
            return

        # ok, call api.readdir to list the directory
        try:
            c_path = c_char_p(path)
            c_file = c_char_p(file)
            c_data = c_void_p(None)
            self.start_clock()
            err = api.hvfs_readdir(c_path, c_file, byref(c_data))
            if err != 0:
                print "api.hvfs_readdir() failed w/ %d" % err
                return
            self.stop_clock()
            c_str = c_char_p(c_data.value)
            print c_str.value
            self.echo_clock("Time elasped:")
            # free the region
            api.hvfs_free(c_data)
        except ValueError, ve:
            print "ValueError %s" % ve
        except IOError, ie:
            print "IOError %s" % ie

    def do_stat(self, line):
        '''Stat a file. If any of the dir does not exist,
        we just reject the operations.
        Usage: stat path/to/name

        Result description:
        puuid(0x) psalt(0x) uuid(0x) flags(0x) uid gid mode(o) 
        nlink size dev atime ctime mtime dtime version 
        {$symlink/$llfs:fsid$llfs:rfino} [column_no stored_itbid len offset]
        '''
        l = shlex.split(line)
        if len(l) < 1:
            print "Invalid argument. See help stat."
            return

        l[0] = os.path.normpath(l[0])
        path, file = os.path.split(l[0])
        if path == "" or path[0] != '/':
            print "Relative path name is not supported yet."
            return

        # ok, call api.stat to stat the file
        try:
            c_path = c_char_p(path)
            c_file = c_char_p(file)
            c_data = c_void_p(None)
            self.start_clock()
            err = api.hvfs_stat(c_path, c_file, byref(c_data))
            if err != 0:
                print "api.hvfs_stat() failed w/ %d" % err
                return
            self.stop_clock()
            c_str = c_char_p(c_data.value)
            print c_str.value
            self.echo_clock("Time elasped:")
            # free the region
            api.hvfs_free(c_data)
        except ValueError, ve:
            print "ValueError %s" % ve

    def do_setattr(self, line):
        '''Set the attributes of a file in current pathname. 
        Usage: setattr /path/to/name key1=value1,key2=value2

        Examples: setattr /abc atime=1000,ctime=500,flag_add=2048

        Result description:
        the column region is always ZERO (please use stat to get the correct values)
        '''
        l = shlex.split(line)
        if len(l) < 2:
            print "Invalid argument. See help setattr."
            return

        l[0] = os.path.normpath(l[0])
        path, file = os.path.split(l[0])
        if path == "" or path[0] != '/':
            print "Relative path name is not supported yet."
            return

        # ok, call api.fupdate to update the file attributes
        try:
            c_path = c_char_p(path)
            c_file = c_char_p(file)
            c_data = cast(c_char_p(l[1]), c_void_p)
            self.start_clock()
            err = api.hvfs_fupdate(c_path, c_file, byref(c_data))
            if err != 0:
                print "api.hvfs_fupdate() failed w/ %d" % err
                return
            self.stop_clock()
            c_str = c_char_p(c_data.value)
            print c_str.value
            self.echo_clock("Time elasped:")
            # free the region
            api.hvfs_free(c_data)
        except ValueError, ve:
            print "ValueError %s" % ve

    def do_cpin(self, line):
        '''Copy a file from local file system to Pomegranate.
        Usage: cpin /path/to/local/file /path/to/hvfs [flag:zip]'''
        l = shlex.split(line)
        if len(l) < 2:
            print "Invalid argument. See help cpin."
            return

        l[0] = os.path.normpath(l[0])
        l[1] = os.path.normpath(l[1])

        flag = 0
        if len(l) == 3:
            if l[2] == "zip":
                flag = 0x02 # SCD_LZO

        path, file = os.path.split(l[1])
        if path == "" or path[0] != '/':
            print "Relative path name is not supported yet."
            return

        # read in the local file 
        try:
            f = open(l[0], 'r')
            content = f.read()
            dlen = f.tell()
        except IOError, ioe:
            print "IOError %s" % ioe
            return

        # write to hvfs and commit metadata (create or update)
        try:
            c_path = c_char_p(path)
            c_file = c_char_p(file)
            c_column = c_int(0)
            c_content = c_char_p(content)
            c_len = c_long(dlen)
            c_flag = c_int(flag)
            self.start_clock()
            err = api.hvfs_fwrite(c_path, c_file, c_column, c_content, c_len, 
                                  c_flag)
            self.stop_clock()
            if err != 0:
                print "api.hvfs_fwrite() failed w/ %d" % err
                return
            else:
                print "+OK"
            self.echo_clock("Time elasped:")
        except IOError, ioe:
            print "IOError %s" % ioe
        except ValueError, ve:
            print "ValueError %s" % ve

    def do_cpout(self, line):
        '''Copy a Pomegranate file to local file system.
        Usage: cpout /path/to/hvfs /path/to/local/file'''
        l = shlex.split(line)
        if len(l) < 2:
            print "Invalid argument. See help cpout."
            return

        l[0] = os.path.normpath(l[0])
        l[1] = os.path.normpath(l[1])

        path, file = os.path.split(l[0])
        if path == "" or path[0] != '/':
            print "Relative path name is not supported yet."
            return

        # read the metadata to find file offset and read in the file content
        try:
            c_path = c_char_p(path)
            c_file = c_char_p(file)
            c_column = c_int(0)
            c_content = c_void_p(None)
            c_len = c_long(0)
            self.start_clock()
            api.hvfs_fread.restype = c_long
            err = api.hvfs_fread(c_path, c_file, c_column, byref(c_content), byref(c_len))
            self.stop_clock()
            if err < 0:
                print "api.hvfs_fread() failed w/ %d" % err
                return
            self.echo_clock("Time elasped:")
        except IOError, ioe:
            print "IOError %s" % ioe
            return

        # write to the local file
        try:
            if l[1] == "$STDOUT$":
                c_str = c_char_p(c_content.value)
                print c_str.value
            else:
                f = open(l[1], "wb")
                f.truncate(0)
                f.close()

                f = libc.open(l[1], 2) # O_RDWR = 0x02
                libc.write.restype = c_long
                bw = long(0)
                save_content = c_void_p(None)
                save_content.value = c_content.value

                while c_len.value > 0:
                    bw = libc.write(f, c_content, c_len)
                    if bw < 0:
                        print "Write failed"
                        break
                    c_content.value += bw
                    c_len.value -= bw

                err = libc.close(f)
                if c_len.value > 0:
                    print "Incomplete write, remain %ld bytes..." % (c_len.value)
                if err != 0:
                    pass
        except IOError, ioe:
            print "IOError %s" % ioe

        api.hvfs_free(save_content)
        print "+OK"

    def do_cat(self, line):
        '''Cat a Pomegranate file's content.
        Usage: cat /path/to/hvfs'''
        l = shlex.split(line)
        if len(l) < 1:
            print "Invalid argument. See help cat."
            return

        l[0] = os.path.normpath(l[0])

        path, file = os.path.split(l[0])
        if path == "" or path[0] != '/':
            print "Relative path name is not supported yet."
            return

        # read the metadata to find file offset and read in the file content
        try:
            c_path = c_char_p(path)
            c_file = c_char_p(file)
            c_column = c_int(0)
            c_content = c_char_p(None)
            c_len = c_long(0)
            self.start_clock()
            err = api.hvfs_fread(c_path, c_file, c_column, byref(c_content), byref(c_len))
            self.stop_clock()
            if err < 0:
                print "api.hvfs_fread() failed w/ %d" % err
                return

            # dump to stdout now
            print c_content.value
            api.hvfs_free(c_content)

            self.echo_clock("Time elasped:")
        except IOError, ioe:
            print "IOError %s" % ioe
            return

    def do_commit(self, line):
        '''Trigger a memory snapshot on the remote MDS.
        Usage: commit #MDS'''
        l = shlex.split(line)
        if len(l) < 1:
            print "Invalid argument. See help commit."
            return
        # ok, transform the id to int
        if l[0] == "all":
            try:
                api.hvfs_active_site.restype = c_char_p
                asites = api.hvfs_active_site("mds")
                lx = shlex.split(asites)
                for x in lx:
                    if x != "" and x != None:
                        id = c_int(int(x))
                        err = api.hvfs_fcommit(id)
                        if err != 0:
                            print "api.hvfs_commit() failed w/ %d" % err
                            return
            except ValueError, ve:
                print "ValueError %s" % ve
        else:
            try:
                id = c_int(int(l[0]))
                err = api.hvfs_fcommit(id)
                if err != 0:
                    print "api.hvfs_commit() failed w/ %d" % err
                    return
            except ValueError, ve:
                print "ValueError %s" % ve
        print "+OK"

    def do_regdtrigger(self, line):
        '''Register a DTrigger on a directory.
        Usage: regdtrigger /path/to/name type where priority /path/to/local/file'''
        l = shlex.split(line)
        if len(l) < 5:
            print "Invalid argumment. Please see help regdtrigger."
            return

        l[0] = os.path.normpath(l[0])
        l[4] = os.path.normpath(l[4])

        path, file = os.path.split(l[0])
        if path == "" or path[0] != '/':
            print "Relative path name is not supported yet."
            return

        content = """def dtdefault(dt):
        return TRIG_CONTINUE"""

        try:
            f = open(l[4], "r")
            content = f.read()
        except IOError, ie:
            print "IOErrror %s" % ie
            return

        # ok
        try:
            c_path = c_char_p(path)
            c_file = c_char_p(file)
            c_type = c_int(int(l[1]))
            c_where = c_short(int(l[2]))
            c_priority = c_short(int(l[3]))
            c_data = c_char_p(content)
            c_len = c_long(len(content))
            err = api.hvfs_reg_dtrigger(c_path, c_file, c_priority,
                                        c_where, c_type, c_data,
                                        c_len)
            if err != 0:
                print "api.hvfs_reg_dtrigger() failed w/ %d" % err
                return
        except ValueError, ve:
            print "ValueError %s" % ve
        print "+OK"

    def do_catdtrigger(self, line):
        '''Cat the DTriggers on a directory.
        Usage: catdtrigger /path/to/name'''
        l = shlex.split(line)
        if len(l) < 1:
            print "Invalid argument. Please see help catdtrigger."
            return

        l[0] = os.path.normpath(l[0])

        path, file = os.path.split(l[0])
        if path == "" or path[0] != '/':
            print "Relative path name is not supported yet."
            return

        # ok
        try:
            c_path = c_char_p(path)
            c_file = c_char_p(file)
            c_data = c_void_p(None)
            err = api.hvfs_cat_dtrigger(c_path, c_file, byref(c_data))
            if err != 0:
                print "api.hvfs_cat_dtrigger() failed w/ %d" % err
                return
        except ValueError, ve:
            print "ValueError %s" % ve
        print "+OK"

    def do_getcluster(self, line):
        '''Get the MDS/MDSL cluster status.
        Usage: getcluster 'mds/mdsl/bp' '''
        l = shlex.split(line)
        if len(l) < 1:
            print "Invalid argument."
            return

        # ok
        try:
            type = c_char_p(l[0])
            err = api.hvfs_get_cluster(type)
            if err != 0:
                print "api.hvfs_get_cluster() failed w/ %d" % err
                return
        except ValueError, ve:
            print "ValueError %s" % ve
        print "+OK"

    def do_getactivesite(self, line):
        '''Get the active sites.
        Usage: getactivesite 'mds/mdsl/bp' '''
        l = shlex.split(line)
        if len(l) < 1:
            print "Invalid argument. See help getactivesite!"
            return
        # ok
        try:
            type = c_char_p(l[0])
            err = api.hvfs_active_site(type)
            if err == None:
                print "api.hvfs_active_site() failed w/ %s" % err
                return
        except ValueError, ve:
            print "ValueError %s" % ve

    def do_getactivesitesize(self, line):
        '''Get the active sites' size. Some from rings and some from R2 server.
        Usage: getactivesite 'mds/mdsl/osd/r2/bp' '''
        l = shlex.split(line)
        if len(l) < 1:
            print "Invalid argument. See help getactivesitesize!"
            return
        # ok
        try:
            type = c_char_p(l[0])
            err = api.hvfs_active_site_size(type)
            if err < 0:
                print "api.hvfs_active_site() failed w/ %d" % err
                return
            else:
                print "Active %s sites: %d" % (l[0], err)
        except ValueError, ve:
            print "ValueError %s" % ve

    def get_bp_cluster_size(self):
        err = api.hvfs_active_site_size("bp")
        if err < 0:
            print "api.hvfs_active_site_size() failed w/ %d" % err
            return
        return range(0, err)

    def do_offline(self, line):
        '''Offline a site or a group of sites.
        Usage: offline 'mds/mdsl' id [force]'''
        force = 0
        l = shlex.split(line)
        if len(l) < 2:
            print "Invalid argument. See help offline!"
            return
        elif len(l) > 2:
            force = l[2]

        # ok
        try:
            self.start_clock()
            err = api.hvfs_offline(l[0], int(l[1]), int(force))
            if err != 0:
                print "api.hvfs_offline() failed w/ %d" % err
                return
            self.stop_clock()
            self.echo_clock("Time elasped:")
        except TypeError, te:
            print "TypeError %s" % te
        except ValueError, ve:
            print "ValueError %s" % ve
        print "+OK"

    def do_online(self, line):
        '''Online a site or a group sites.
        Usage: online 'mds/mdsl' id'''
        l = shlex.split(line)
        if len(l) < 2:
            print "Invalid argument. See help online!"
            return
        # ok
        try:
            self.start_clock()
            err = api.hvfs_online(l[0], int(l[1]))
            if err != 0:
                print "api.hvfs_online() failed w/ %d" % err
                return
            self.stop_clock()
            self.echo_clock("Time elasped:")
        except TypeError, te:
            print "TypeError %s" % te
        except ValueError, ve:
            print "ValueError %s" % ve
        print "+OK"

    def do_addsite(self, line):
        '''Online add a new site.
        Usage: addsite ip port type id'''
        l = shlex.split(line)
        if len(l) < 4:
            print "Invalid arguments. See help addsite!"
            return
        # ok
        try:
            self.start_clock()
            err = api.hvfs_addsite(l[0], int(l[1]), l[2], int(l[3]))
            if err != 0:
                print "api.hvfs_addsite() failed w/ %d" % err
                return
            self.stop_clock()
            self.echo_clock("Time elasped:")
        except TypeError, te:
            print "TypeError %s" % te
        except ValueError, ve:
            print "ValueError %s" % ve

    def do_rmvsite(self, line):
        '''Remove a site from the address table
        Usage: rmvsite ip port site_id'''
        l = shlex.split(line)
        if len(l) < 3:
            print "Invalid arguments. See help rmvsite!"
            return
        # ok
        try:
            self.start_clock()
            err = api.hvfs_rmvsite(l[0], int(l[1]), long(l[2]))
            if err != 0:
                print "api.hvfs_rmvsite() failed w/ %d" % err
                return
            self.stop_clock()
            self.echo_clock("Time elasped:")
        except TypeError, te:
            print "TypeError %s" % te
        except ValueError, ve:
            print "ValueError %s" % ve

    def do_shutdown(self, line):
        '''Shutdown a opened but ERROR state site entry @ R2 server
        Usage: shutdown site_id'''
        l = shlex.split(line)
        if len(l) < 1:
            print "Invalid arguments. See help shutdown!"
            return
        # ok
        try:
            self.start_clock()
            err = api.hvfs_shutdown(long(l[0]))
            if err != 0:
                print "api.hvfs_shutdown() failed w/ %d" % err
                return
            self.stop_clock()
            self.echo_clock("Time elasped:")
        except TypeError, te:
            print "TypeError %s" % te
        except ValueError, ve:
            print "ValueError %s" % ve

    def do_statfs(self, line):
        '''Statfs to get the metadata of the file system.
        Usage: statfs'''

        try:
            c_data = c_void_p(None)
            self.start_clock()
            err = api.hvfs_statfs(byref(c_data))
            if err != 0:
                print "api.hvfs_statfs() failed w/ %d" % err
                return
            self.stop_clock()
            c_str = c_char_p(c_data.value)
            print c_str.value
            self.echo_clock("Time elasped:")
            # free the region
            api.hvfs_free(c_data)
        except ValueError, ve:
            print "ValueError %s" % ve

    def do_cbranch(self, line):
        '''Create a new branch.
        Usage: cbranch branch_name tag level "op,op,..."
               filter:id:rid:<l|r>[:<reg>]
               sum:id:rid:<l|r>[:<reg>:[left|right|all|match]]
               count:id:rid:<l|r>[:<reg>:[left|right|all|match]]
               avg:id:rid:<l|r>[:<reg>:[left|right|all|match]]
               max:id:rid:<l|r>[:<reg>:[left|right|all|match]]
               min:id:rid:<l|r>[:<reg>:[left|right|all|match]]
               knn:id:rid:<l|r>:<reg>:<left|right|all|match>:type:center:+/-distance
               groupby:id:rid:<l|r>:<reg>:<left|right|all|match>:[sum/avg/max/min/count]
               indexer:id:rid:<l|r>:<plain|bdb>:<dbname>:<prefix>
        '''
        l = shlex.split(line)
        if len(l) < 3:
            print "Invalid arguments. See help cbranch/bc!"
            return
        ops = None
        if len(l) >= 4:
            l[3] = l[3].replace(",", " ")
            l[3] = shlex.split(l[3])
            nr = 0
            ops = struct_branch_ops()
            for x in l[3]:
                # split the operator description
                y = x.replace(":", " ")
                y = y.replace(";", " ")
                y = shlex.split(y)
                if len(y) < 4:
                    print "Ignore this OP '%s'" % x
                    continue

                x = y[0]
                op = struct_branch_op()
                op.len = 0
                op.data = c_void_p(None)
                op.id = c_uint32(int(y[1]))
                op.rid = c_uint32(int(y[2]))
                if y[3].lower() == "l":
                    op.lor = 0
                elif y[3].lower() == "r":
                    op.lor = 1
                else:
                    print "Invalid op lor value '%s'" % y[3]
                    continue

                if x.lower() == "filter":
                    if len(y) == 5:
                        s = "rule:" + y[4] + ";output_filename:f" + y[1]
                    else:
                        s = "rule:.*;output_filename:log" + y[1]
                    op.op = op.FILTER
                    op.data = cast(c_char_p(s), c_void_p)
                    op.len = c_uint32(len(s))
                    ops.ops[nr] = op
                    nr += 1
                elif x.lower() == "sum":
                    if len(y) == 6:
                        s = "rule:" + y[4] + ";lor:" + y[5]
                    elif len(y) == 5:
                        s = "rule:" + y[4] + ";lor:all"
                    else:
                        s = "rule:.*;lor:all"
                    op.op = op.SUM
                    op.data = cast(c_char_p(s), c_void_p)
                    op.len = c_uint32(len(s))
                    ops.ops[nr] = op
                    nr += 1
                elif x.lower() == "count":
                    if len(y) == 6:
                        s = "rule:" + y[4] + ";lor:" + y[5]
                    elif len(y) == 5:
                        s = "rule:" + y[4] + ";lor:all"
                    else:
                        s = "rule:.*;lor:all"
                    op.op = op.COUNT
                    op.data = cast(c_char_p(s), c_void_p)
                    op.len = c_uint32(len(s))
                    ops.ops[nr] = op
                    nr += 1
                elif x.lower() == "avg":
                    if len(y) == 6:
                        s = "rule:" + y[4] + ";lor:" + y[5]
                    elif len(y) == 5:
                        s = "rule:" + y[4] + ";lor:all"
                    else:
                        s = "rule:.*;lor:all"
                    op.op = op.AVG
                    op.data = cast(c_char_p(s), c_void_p)
                    op.len = c_uint32(len(s))
                    ops.ops[nr] = op
                    nr += 1
                elif x.lower() == "max":
                    if len(y) == 6:
                        s = "rule:" + y[4] + ";lor:" + y[5]
                    elif len(y) == 5:
                        s = "rule:" + y[4] + ";lor:all"
                    else:
                        s = "rule:.*;lor:all"
                    op.op = op.MAX
                    op.data = cast(c_char_p(s), c_void_p)
                    op.len = c_uint32(len(s))
                    ops.ops[nr] = op
                    nr += 1
                elif x.lower() == "min":
                    if len(y) == 6:
                        s = "rule:" + y[4] + ";lor:" + y[5]
                    elif len(y) == 5:
                        s = "rule:" + y[4] + ";lor:all"
                    else:
                        s = "rule:.*;lor:all"
                    op.op = op.MIN
                    op.data = cast(c_char_p(s), c_void_p)
                    op.len = c_uint32(len(s))
                    ops.ops[nr] = op
                    nr += 1
                elif x.lower() == "knn":
                    if len(y) == 9:
                        s = "rule:" + y[4] + ";lor:" + y[5] + ";knn:" + y[6] + ":" + y[7] + ":" + y[8]
                    elif len(y) == 8:
                        s = "rule:" + y[4] + ";lor:" + y[5] + ";knn:" + y[6] + ":" + y[7] + ":+-1"
                    elif len(y) == 7:
                        s = "rule:" + y[4] + ";lor:" + y[5] + ";knn:" + y[6] + ":0:+-1"
                    elif len(y) == 6:
                        s = "rule:" + y[4] + ";lor:" + y[5] + ";knn:linear:0:+-1"
                    elif len(y) == 5:
                        s = "rule:" + y[4] + ";lor:all;knn:linear:0:+-1"
                    else:
                        s = "rule:.*;lor:all;knn:linear:0:+-1"
                    op.op = op.KNN
                    op.data = cast(c_char_p(s), c_void_p)
                    op.len = c_uint32(len(s))
                    ops.ops[nr] = op
                    nr += 1
                elif x.lower() == "groupby":
                    if len(y) == 7:
                        s = "rule:" + y[4] + ";lor:" + y[5] + ";groupby:" + y[6]
                    elif len(y) == 6:
                        s = "rule:" + y[4] + ";lor:" + y[5] + ";groupby:count"
                    elif len(y) == 5:
                        s = "rule:" + y[4] + ";lor:all;groupby:count"
                    else:
                        s = "rule:.*;lor:all;groupby:count"
                    op.op = op.GROUPBY
                    op.data = cast(c_char_p(s), c_void_p)
                    op.len = c_uint32(len(s))
                    ops.ops[nr] = op
                    nr += 1
                elif x.lower() == "rank":
                    op.op = op.RANK
                    ops.ops[nr] = op
                    nr += 1
                elif x.lower() == "indexer":
                    if len(y) == 7:
                        s = "type:" + y[4] + ";schema:" + y[5] + ":" + y[6]
                    elif len(y) == 6:
                        s = "type:" + y[4] + ";schema:" + y[5] + ":default"
                    elif len(y) == 5:
                        s = "type:" + y[4] + ";schema:default_db:default"
                    else:
                        s = "type:plain;schema:default_db:default"
                    op.op = op.INDEXER
                    op.data = cast(c_char_p(s), c_void_p)
                    op.len = c_uint32(len(s))
                    ops.ops[nr] = op
                    nr += 1
                elif x.lower() == "codec":
                    op.op = op.CODEC
                    ops.ops[nr] = op
                    nr += 1
                if nr >= 10:
                    print "At most ten valid operators, ignore others!"
                    break
            ops.nr = c_uint32(nr)

        # ok
        try:
            self.start_clock()
            if ops == None:
                err = branch.branch_create(c_int(0), c_int(0), c_char_p(l[0]), 
                                           c_char_p(l[1]), c_int(int(l[2])), 
                                           c_void_p(None))
            else:
                err = branch.branch_create(c_int(0), c_int(0), c_char_p(l[0]), 
                                           c_char_p(l[1]), c_int(int(l[2])), 
                                           cast(pointer(ops), c_void_p))
            if err != 0:
                print "branch.branch_create() failed w/ %d" % err
                return
            self.stop_clock()
            self.echo_clock("Time elasped:")
        except TypeError, te:
            print "TypeError %s" % te
        except ValueError, ve:
            print "ValueError %s" % ve

    def do_bc(self, line):
        '''Create a new branch, same as cbranch.
        Usage: bc branch_name tag level "op,op,..."'''
        return self.do_cbranch(line)

    def do_bp(self, line):
        '''Publish a new branch line.
        Usage: bp branch_name tag level DATA_STRING'''
        if not self.use_branch:
            print "You have to enable branch feeder mode."
            return
        l = shlex.split(line)
        if len(l) < 4:
            print "Invalid arguments, See help bp!"
            return
        # ok
        try:
            self.start_clock()
            err = branch.branch_publish(c_uint64(0), c_uint64(0), c_char_p(l[0]),
                                        c_char_p(l[1]), c_uint8(int(l[2])),
                                        c_char_p(l[3]), c_uint64(len(l[3])))
            if err != 0:
                print "branch.branch_publish() failed w/ %d" % err
                return
            self.stop_clock()
            self.echo_clock("Time elasped:")
        except TypeError, te:
            print "TypeError %s" % te
        except ValueError, ve:
            print "ValueError %s" % ve

    def do_getbor(self, line):
        '''Get a BOR from a BP site.
        Usage: getbor branch_name bpsite'''
        l = shlex.split(line)
        if len(l) < 2:
            print "Invalid arguments, See help getbor!"
            return
        # ok
        try:
            self.start_clock()
            err = branch.branch_dumpbor(c_char_p(l[0]), c_uint64(int(l[1])))
            if err != 0:
                print "branch.branch_dumpbor() failed w/ %d" % err
                return
            self.stop_clock()
            self.echo_clock("Time elasped:")
        except TypeError, te:
            print "TypeError %s" % te
        except ValueError, ve:
            print "ValueError %s" % ve

    def do_search(self, line):
        '''Search a EXPR from a BP site.
        Usage: search branch_name bpsite dbname prefix EXPR

        Example: search branch_name 0 dbname prefix "r:type=png & tag:color=rgb"'''

        l = shlex.split(line)
        if len(l) < 5:
            print "Invalid arguments, See help search!"
            return
        # ok
        try:
            if str(l[1]) != "all":
                bplist = [int(l[1])]
            else:
                bplist = self.get_bp_cluster_size()

            self.start_clock()
            for idx in bplist:
                c_data = c_void_p(None)
                c_size = c_uint64(0);
                c_str = c_char_p(None)
                err = branch.branch_search(c_char_p(l[0]), c_uint64(int(idx)),
                                           c_char_p(l[2]), c_char_p(l[3]),
                                           c_char_p(l[4]), byref(c_data), 
                                           byref(c_size))
                if err == -22:
                    # ignore this error
                    continue
                elif err != 0:
                    print "branch.branch_search() failed w/ %d" % err
                    return
                branch.branch_dumpbase(c_data, c_size, byref(c_str))
                print c_str.value
                c_data2 = c_void_p(None)
                c_nr = c_int(0)
                c_data3 = c_char_p(None)
                branch.branch_base2fh(c_data, c_size, byref(c_data2), byref(c_nr))
                api.hvfs_ploop(c_data2, c_nr, api.hvfs_pstat, byref(c_data3), byref(c_size))
                print c_data3.value
                api.hvfs_free(c_data3)
                api.hvfs_free(c_data2)
                api.hvfs_free(c_data)
                api.hvfs_free(c_str)

            self.stop_clock()
            
            self.echo_clock("Time elasped+p:")
        except TypeError, te:
            print "TypeError %s" % te
        except ValueError, ve:
            print "ValueError %s" % ve

    def do_pst(self, line):
        '''Print the xnet site table.
        Usage: pst
        '''

        xnet.st_print()

    def do_clrdtrigger(self, line):
        '''Clear ALL the attached DTriggers.
        Usage: clrdtrigger /path/to/name
        '''
        l = shlex.split(line)
        if len(l) < 1:
            print "Invalid argument. Please see help clrdtrigger."
            return

        l[0] = os.path.normpath(l[0])

        path, file = os.path.split(l[0])
        if path == "" or path[0] != '/':
            print "Relative path name is not supported yet."
            return

        # ok
        try:
            c_path = c_char_p(path)
            c_file = c_char_p(file)
            err = api.hvfs_clear_dtrigger(c_path, c_file)
            if err != 0:
                print "api.hvfs_clear_dtrigger() failed w/ %d" % err
                return
        except ValueError, ve:
            print "ValueError %s" % ve
        print "+OK"

    def do_getinfo(self, line):
        '''Get system info from R2.
        Usage: getinfo [all|site|mds|mdsl] [all|mds|mdsl|client|bp|r2||raw|rate]
                       site [all|mds|mdsl|client|bp|r2]
                       mds  [rate|raw]
        '''
        l = shlex.split(line)
        cmd = 0
        arg = 0

        if len(l) == 0:
            cmd = 100
        elif len(l) >= 1:
            if l[0] == "all":
                cmd = 100
            elif l[0] == "site":
                cmd = 1
            elif l[0] == "mds":
                cmd = 2
            elif l[0] == "mdsl":
                cmd = 3
            else:
                cmd = 0
        if len(l) >= 2:
            if l[1] == "all":
                arg = 0
            elif l[1] == "mds":
                arg = 1
            elif l[1] == "mdsl":
                arg = 2
            elif l[1] == "client":
                arg = 3
            elif l[1] == "bp":
                arg = 4
            elif l[1] == "r2":
                arg = 5
            elif l[1] == "rate":
                arg = 0
            elif l[1] == "raw":
                arg = 1

        c_str = c_char_p(None)
        err = api.hvfs_get_info(cmd, arg, byref(c_str));
        if err != 0:
            print "api.hvfs_get_info() failed w/ %d" % err
            return
        print c_str.value
        api.hvfs_free(c_str)
        print "+OK"

    def do_analysestorage(self, line):
        '''Analyse the storage txg log file for some mds sites
        Usage: analysestorage site_id [txg|list]
        '''
        site = 0
        type = 1
        max = 0
        length = 8
        l = shlex.split(line)

        try:
            if len(l) < 1:
                print "Usage: analysestorage site_id type."
                return
            elif len(l) == 1:
                site = int(l[0])
                type = 1
            elif len(l) >= 2:
                site = int(l[0])
                if l[1] == 'txg':
                    type = 1
                elif l[1] == 'list':
                    type = 2
                else:
                    print "Usage: analysestroage site_id [txg|list]."
                    return
        except ValueError, ve:
            print "Invalid argument: %s" % ve
            return

        site = HVFS_MDS(site)
        print "Analyse TXG log file for site: %x" % site

        c_data = c_void_p(max)
        c_len = c_long(length)
        err = api.hvfs_analyse_storage(c_long(site), c_int(type), 
                                       byref(c_data), byref(c_len))
        if type == 1:
            max = c_data.value
        if err != 0:
            print "api.hvfs_analyse_storage() failed w/ %d" % err
            return
        print "MAX TXG: " + str(max)
        print "+OK"

    def do_queryobj(self, line):
        '''Query the active OSD sites which contains the object 
        Usage: queryobj file_uuid file_blockid'''
        l = shlex.split(line)
        if len(l) < 2:
            print "Invalid argument. See help queryobj!"
            return

        # ok
        try:
            self.start_clock()
            api.hvfs_query_obj_print(long(l[0]), int(l[1]))
            self.stop_clock()
            self.echo_clock("Time elasped:")
        except TypeError, te:
            print "TypeError %s" % te
        except ValueError, ve:
            print "ValueError %s" % ve
        print "+OK"

    def do_writeobj(self, line):
        '''Write the object data region to the specified OSD.
        Usage: writeobj file_uuid file_blockid OSD#i string offset'''
        l = shlex.split(line)
        if len(l) < 5:
            print "Invalid argument. See help writeobj!"
            return
        print l

        # ok
        try:
            self.start_clock()
            site = HVFS_OSD(l[2])
            c_data = c_char_p(l[3])
            err = api.hvfs_write_obj(long(l[0]), int(l[1]), long(site),
                                     c_data, int(len(l[3])), 
                                     long(l[4]))
            if err != 0:
                print "api.hvfs_write_obj() failed w/ %d" % err
                return
            print "+OK"
        except TypeError, te:
            print "TypeError %s" % te
        except ValueError, ve:
            print "ValueError %s" % ve

    def do_readobj(self, line):
        '''Read the object data region from the specified OSD.
        Usage: readobj file_uuid file_blockid OSD#i length offset'''
        l = shlex.split(line)
        if len(l) < 5:
            print "Invalid argument. See help readobj!"
            return

        # ok
        try:
            self.start_clock()
            site = HVFS_OSD(l[2])
            c_data = c_char_p(None)
            err = api.hvfs_read_obj(long(l[0]), int(l[1]), long(site),
                                    byref(c_data), int(l[3]),
                                    long(l[4]), long(-1))
            if err < 0:
                print "api.hvfs_read_obj() failed w/ %d" % err
                return
            print c_data.value
            api.hvfs_free(c_data)
            print "+OK"
        except TypeError, te:
            print "TypeError %s" % te
        except ValueError, ve:
            print "ValueError %s" % ve

    def do_delobj(self, line):
        '''Del the object from the specified OSD.
        Usage: delobj file_uuid file_blockid OSD#i'''
        l = shlex.split(line)
        if len(l) < 3:
            print "Invalid argument. See help readobj!"
            return

        # ok
        try:
            self.start_clock()
            site = HVFS_OSD(l[2])
            c_data = c_char_p(None)
            err = api.hvfs_del_obj(long(l[0]), int(l[1]), long(site))
            if err < 0:
                print "api.hvfs_del_obj() failed w/ %d" % err
                return
            print "+OK"
        except TypeError, te:
            print "TypeError %s" % te
        except ValueError, ve:
            print "ValueError %s" % ve

    def do_truncobj(self, line):
        '''Truncate the object from specified OSD.
        Usage: truncobj file_uuid file_blockid OSD#i length'''
        l = shlex.split(line)
        if len(l) < 4:
            print "Invalid argument. See help readobj!"
            return

        # ok
        try:
            self.start_clock()
            site = HVFS_OSD(l[2])
            err = api.hvfs_trunc_obj(long(l[0]), int(l[1]), long(site), long(l[3]))
            if err < 0:
                print "api.hvfs_trunc_obj() failed w/ %d" % err
                return
            print "+OK"
        except TypeError, te:
            print "TypeError %s" % te
        except ValueError, ve:
            print "ValueError %s" % ve

    def do_quit(self, line):
        print "Quiting ..."
        return True

    def do_EOF(self, line):
        print "Quiting ..."
        return True

def print_help():
    print "FS Demo Client: "
    print " -h, --help          print this help document."
    print " -t, --thread        how many threads do you want to run.(IGNORED)"
    print " -i, --id            the logical id of this FS client."
    print " -r, --ring          the R2 server ip address."
    print " -b, --use_branch    init branch client."

if __name__ == '__main__':
    main(sys.argv[1:])
