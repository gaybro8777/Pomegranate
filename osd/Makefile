##
# Copyright (c) 2009 Ma Can <ml.macana@gmail.com>
#                           <macan@ncic.ac.cn>
#
# Time-stamp: <2012-08-10 13:59:50 macan>
#
# This is the makefile for HVFS project.
#
# Armed with EMACS.

include ../Makefile.inc

all : osd_lib

%.o : %.c $(osd_h_depend_files)
	@$(ECHO) -e " " CC"\t" $@
	@$(CC) $(CFLAGS) -c $(patsubst %.c, $(OSD)/%.c, $<)

osd_lib : $(OSD_AR_SOURCE:.c=.o)
	@$(ECHO) -e " " AR"\t" $@
	@$(AR) rcs libosd.a $(^:.c=.o)
	@$(ECHO) -e " " SL"\t" $(OSD_SO)
	@$(CC) -shared -Wl,-soname,libosd.so.1 -o $(LIB_PATH)/libosd.so.1.0 $(^:.c=.o) -lc -lrt -lpthread

clean : 
	-@rm -rf $(OSD_AR_SOURCE:.c=.o)
	-@rm -rf libosd.a $(LIB_PATH)/libosd.so.1.0