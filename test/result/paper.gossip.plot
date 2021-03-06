# Template for plot mds pictures
#
# Copyright (c) Ma Can <ml.macana@gmail.com>
#                      <macan@ncic.ac.cn>
#
reset
set terminal postscript eps enhanced color
#set terminal png transparent
set origin 0.0, 0.0
set size 1, 1
set grid
set output "paper.gossip.eps"
#set output "paper.gossip.png"
set auto x
set xtics out
set auto y

set xrange [0:180]

set multiplot layout 2,1
set xlabel "TimeStamp (s)"
set ylabel "Request per Second (#/s)"
set ytics nomirror
set format y "%gK"
set y2label "# of Requests (#)"
set y2tics
set format y2 "%gK"
set key right top 
set title "Without Gossip"

plot "< awk '{if (ts == 0) {ts = $2; modify = $5;} \
              {print ($2 - ts)\" \"(($5 - modify)/5.0/1000);} \
              modify = $5;}' ./CP-BACK-mds.aggr" \
     using 1:2 t "Create RPS" w linesp ls 2 axes x1y1, \
     "< awk '{if (ts == 0) {ts = $2; fwds = $15;} \
              {print ($2 - ts)\" \"($15 - fwds)/1000;} \
              fwds = $15;}' ./CP-BACK-mds.aggr"\
     using 1:2 t "Request Forwarded" w linesp ls 1 axes x1y2, \
     "< awk '{if (ts == 0) {ts = $2; loop_fwds = $24;} \
              {print ($2 - ts)\" \"($24 - loop_fwds)/1000;} \
              loop_fwds = $24;}' ./CP-BACK-mds.aggr" \
     using 1:2 t "Looped Forwards" w linesp ls 4 axes x1y2

set title "With Dynamically Gossip"

plot "< awk '{if (ts == 0) {ts = $2; modify = $5;} \
              {print ($2 - ts)\" \"(($5 - modify)/5.0/1000);} \
              modify = $5;}' xnet/CP-BACK-mds.aggr" \
     using 1:2 t "Create RPS" w linesp ls 2 axes x1y1, \
     "< awk '{if (ts == 0) {ts = $2; fwds = $15;} \
              {print ($2 - ts)\" \"($15 - fwds)/1000;} \
              fwds = $15;}' xnet/CP-BACK-mds.aggr"\
     using 1:2 t "Request Forwarded" w linesp ls 1 axes x1y2, \
     "< awk '{if (ts == 0) {ts = $2; loop_fwds = $24;} \
              {print ($2 - ts)\" \"($24 - loop_fwds)/1000;} \
              loop_fwds = $24;}' xnet/CP-BACK-mds.aggr" \
     using 1:2 t "Looped Forwards" w linesp ls 4 axes x1y2

