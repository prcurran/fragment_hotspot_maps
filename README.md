# Welcome to the Hotspots API!

[![Documentation Status](https://readthedocs.org/projects/hotspots/badge/?version=latest)](https://hotspots.readthedocs.io/en/latest/?badge=latest)
[![License](http://img.shields.io/badge/license-MIT-blue.svg?style=flat)](https://github.com/prcurran/fragment_hotspot_maps/blob/master/LICENSE)
[![Total alerts](https://img.shields.io/lgtm/alerts/g/prcurran/fragment_hotspot_maps.svg?logo=lgtm&logoWidth=18)](https://lgtm.com/projects/g/prcurran/fragment_hotspot_maps/alerts/)
[![Language grade: Python](https://img.shields.io/lgtm/grade/python/g/prcurran/fragment_hotspot_maps.svg?logo=lgtm&logoWidth=18)](https://lgtm.com/projects/g/prcurran/fragment_hotspot_maps/context:python)
[![Language grade: JavaScript](https://img.shields.io/lgtm/grade/javascript/g/prcurran/fragment_hotspot_maps.svg?logo=lgtm&logoWidth=18)](https://lgtm.com/projects/g/prcurran/fragment_hotspot_maps/context:javascript)


![fragment hotspots](http://fragment-hotspot-maps.ccdc.cam.ac.uk/static/cover_small.jpg)


The Hotspots API is the python package for the Fragment Hotspot Maps project, a knowledge-based method for determining small molecule binding "hotspots" 

For more information on this method: 

    - Radoux, C.J. et. al., Identifying the Interactions that Determine Fragment Binding at Protein Hotspots J. Med. Chem. 2016, 59 (9), 4314-4325 [dx.doi.org/10.1021/acs.jmedchem.5b01980]


***************
Getting Started
***************

Although the Hotspots API is publicly available under the MIT license, it is dependant on the CSD python API - a commercial package. 
If you are an academic user, it's likely your institution will have a license. If you are unsure if you have a 
license or would like to enquire about purchasing one, please contact support@ccdc.cam.ac.uk


Please note, this is an academic project and we would therefore welcome feedback, contributions and collaborations.
If you have any queries regarding this package please contact us (pcurran@ccdc.cam.ac.uk)!


NB: We recommend installing on a Linux machine


Installation
===================

-------------------------
Step 1: Install CSDS 2019
-------------------------
Available from CCDC downloads page 
https://www.ccdc.cam.ac.uk/support-and-resources/csdsdownloads/


You will need a valid site number and confirmation code, this will have been emailed to you when you bought your CSDS 2019 license

You may need to set the following environment variables:

    export CSDHOME=<path_to_CSDS_installation>/CSD_2019




-------------------------
Step 2: Install Ghecom
-------------------------
Available from Ghecom download page
<http://strcomp.protein.osaka-u.ac.jp/ghecom/download_src.html>

"The source code of the ghecom is written in C, and developed and executed on
the linux environment (actually on the Fedora Core).  For the installation,
you need the gcc compiler.  If you do not want to use it, please change the
"Makefile" in the "src" directory."

Download the file "ghecom-src-[date].tar.gz" file.


    tar zxvf ghecom-src-[date].tar.gz
    cd src
    make
    export GHECOM_EXE="<download_directory>"
	
	
------------------------------------------------
Step 3: Create a conda environment (recommended)
------------------------------------------------

    conda create -n hotspots_env python=2.7

------------------------------------------------
Step 4: Install RDKit and CSD python API
------------------------------------------------
Download the standalone CSD python API package from 
https://www.ccdc.cam.ac.uk/forum/csd_python_api/General/06004d0d-0bec-e811-a889-005056977c87


	conda install -c rdkit -n hotspots_env rdkit
	conda install csd-python-api-2.x.x-linux-py2.7-conda.tar.bz2
	
------------------------------------------------
Step 5: Install Hotspots API
------------------------------------------------

    source activate hotspots_env
    pip install hotspots

------------------------------------------------

... and you're ready to go!
