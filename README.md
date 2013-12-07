SPADE-FB
========

Facebook Reporter for [SPADE](http://code.google.com/p/data-provenance/). It accesses Facebook data using [FBConsole](https://github.com/facebook/fbconsole) running using the Jython interpreter and connects to SPADE's DSL reporter using pipes.

Usage
=====

First run SPADE and [add DSL reporter](https://code.google.com/p/data-provenance/wiki/ControlClient). Then run `./run.sh` to start collecting data from Facebook and feed to SPADE.

You can view the collected data by [exporting it in Graphviz format](https://code.google.com/p/data-provenance/wiki/Graphviz) or by using [SPADE's query client](https://code.google.com/p/data-provenance/wiki/QueryClient).
