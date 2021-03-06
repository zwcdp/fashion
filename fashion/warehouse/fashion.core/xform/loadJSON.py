'''
Created on 2018-12-21

Copyright (c) 2018 Bradford Dillman

Load models from JSON files.
'''

import glob
import json
import logging
import os

from munch import munchify

# Module level code is executed when this file is loaded.
# cwd is where segment file was loaded.

def init(moduleConfig, codeRegistry, verbose=False, tags=None):
    '''
    Create 1 LoadJSON object for each file.
    cwd is where segment file was loaded.
    '''
    if isinstance(moduleConfig.parameters.filename, list):
        filenames = moduleConfig.filename
    else:
        filenames = glob.glob(moduleConfig.parameters.filename)
    cfg = munchify(moduleConfig.parameters)
    del cfg.filename
    for fn in filenames:
        codeRegistry.addXformObject(LoadJSON(moduleConfig.moduleName, cfg, fn))

class LoadJSON(object):
    '''
    Generate output by merging a model into a template to produce a file.
    '''

    def __init__(self, moduleName, cfg, filename):
        '''
        Constructor.
        cwd is where segment file was loaded.
        '''
        self.version = "1.0.0"
        self.templatePath = []
        self.config = cfg
        self.filename = os.path.abspath(filename)
        self.name = moduleName + "::" + self.filename
        self.tags = [ "input" ]
        self.inputKinds = []
        self.outputKinds = [ self.config.kind, 'fashion.core.input.file' ]

    def execute(self, codeRegistry, verbose=False, tags=None):
        '''
        Load the JSON file and insert it into the model database.
        cwd is project root.
        '''
        mdb = codeRegistry.getService('fashion.prime.modelAccess')
        with open(str(self.filename), 'r') as fd:
            mdb.inputFile(str(self.filename))
            obj = munchify(json.loads(fd.read()))
            if self.config.isList == False:
                mdb.insert(self.config.kind, obj)
            else:
                for o in obj:
                    mdb.insert(self.config.kind, o)
