'''
Created on 2018-12-28

Copyright (c) 2018 Bradford Dillman

@author: Bradford Dillman

A wrapper around the database to track database operations.

ModelAccess provides a more abstract interface to the database suited for
models. All models are associated with a 'kind', a string name. When using
a ModelAccess, you must provide the database and schema repository to use, 
and a context object. 

The context object must have a unique name to identify the use of the database. 
This is typically the unique name of an xform module or xform object. 

The context object also has 2 lists, inputKinds and outputKinds. These lists 
limit the valid use of the database in this context to searching and reading 
only those kinds in inputKinds, and writing only those kinds in outputKinds. 

The reason these limits are enforced, is because the xform objects are 
scheduled by their dependencies. Xform objects which use a kind listed in
their inputKinds, are scheduled to execute after all the xform objects which
list that kind in the outputKinds.

ModelAccessContext tracks the operations performed on the database. These are
used to delete records inserted the last time a context was used.

The reason ModelAccessContext is a separate class (and not collapsed into
ModelAccess) is that someday, nested contexts might be supported (right now 
they aren't). Right now, you can open and use multiple ModelAccess objects
simultaneously with different contexts. Simultaneous re-use of a context
is undefined. 

Nested access would put a context under a parent context, and if the parent 
context were reset, it would recursivly reset all child contexts. Someday.
'''

import copy
import logging

from jsonschema import ValidationError
from munch import Munch
from tinydb import Query, where

from fashion.databaseAccess import DatabaseAccess


class ModelAccessContext(object):
    '''Record activity in a single context of model access.'''

    def __init__(self, dba, schemaRepo, contextObj):
        '''
        Constructor.
        :param dba: the database to use.
        :param schemaRepo: the SchemaRepository to use for validating objects.
        :param contextObj: the context with name, inputKinds and outputKinds.
        '''
        self.dba = dba
        self.repo = schemaRepo
        self.contextObj = contextObj
        self.properties = Munch()
        self.properties.templatePath = contextObj.templatePath
        self.properties.name = contextObj.name
        self.properties.inputKinds = contextObj.inputKinds
        self.properties.outputKinds = contextObj.outputKinds
        self.properties.insert = {}
        self.properties.search = {}
        self.properties.update = {}
        self.properties.remove = {}
        self.insertStore = {}
        self.searchStore = {}
        self.updateStore = {}
        self.removeStore = {}

    def reset(self):
        '''
        Delete all database records created under this context.
        '''
        oldCtxList = self.dba.table('fashion.model.context').search(
            where('name') == self.properties.name)
        if len(oldCtxList) == 0:
            return
        if len(oldCtxList) > 1:
            logging.error("multiple context error")
        for oldCtx in oldCtxList:
            # delete old context objects, if any
            for kind, ids in oldCtx["insert"].items():
                self.dba.table(kind).remove(doc_ids=ids)
            self.dba.table('fashion.model.context').remove(
                where('name') == self.properties.name)

    def finalize(self):
        '''
        Store the activity collected in this context.
        '''
        # normalize sets into lists
        self.normalize(self.insertStore, self.properties.insert)
        self.normalize(self.searchStore, self.properties.search)
        self.normalize(self.updateStore, self.properties.update)
        self.normalize(self.removeStore, self.properties.remove)
        self.dba.table('fashion.model.context').insert(self.properties)

    def normalize(self, inStore, outStore):
        for kind, idSet in inStore.items():
            outStore[kind] = list(idSet)

    def recordAccess(self, store, kind, id):
        '''
        Record an access.
        :param store: where to record the access.
        :param kind: the model kind accessed.
        :param id: doc_id of the model accessed.
        '''
        if kind not in store:
            store[kind] = set()
        store[kind].add(id)

    def insert(self, kind, model):
        '''
        Insert a model.
        :param kind: the string name of the kind of model to insert.
        :param model: the model object to insert.
        '''
        try:
            self.repo.validate(kind, model)
        except ValidationError:
            logging.error("Validation error: kind={0}".format(kind))
            return None
        id = None
        if kind in self.properties.outputKinds:
            id = self.dba.table(kind).insert(model)
            self.recordAccess(self.insertStore, kind, id)
        else:
            logging.error(
                "attempt to write unlisted outputKind {0}".format(kind))
        return id

    def setSingleton(self, kind, model):
        try:
            self.repo.validate(kind, model)
        except ValidationError:
            logging.error("Validation error: kind={0}".format(kind))
            return None
        id = None
        if kind in self.properties.outputKinds:
            self.dba.table(kind).purge()
            id = self.dba.table(kind).insert(model)
            self.recordAccess(self.insertStore, kind, id)
        else:
            logging.error(
                "attempt to write unlisted outputKind {0}".format(kind))
        return id

    def getSingleton(self, kind):
        if kind in self.properties.inputKinds:
            objs = self.dba.table(kind).all()
            if len(objs) == 0:
                return None
            obj = objs[0]
            self.recordAccess(self.searchStore, kind, obj.doc_id)
            return obj
        else:
            logging.error(
                "attempt to getByKind unlisted inputKind {0}".format(kind))
            return None


    def search(self, kind, q):
        '''
        Query within a model kind.
        :param kind: the model kind to be searched.
        :param q: the query to perform.
        '''
        if kind in self.properties.inputKinds:
            objs = self.dba.table(kind).search(q)
            for o in objs:
                self.recordAccess(self.searchStore, kind, o.doc_id)
            return objs
        else:
            logging.error(
                "attempt to search unlisted inputKind {0}".format(kind))
            return []

    def getByKind(self, kind):
        if kind in self.properties.inputKinds:
            objs = self.dba.table(kind).all()
            for o in objs:
                self.recordAccess(self.searchStore, kind, o.doc_id)
            return objs
        else:
            logging.error(
                "attempt to getByKind unlisted inputKind {0}".format(kind))
            return []

    def getById(self, kind, id):
        if kind in self.properties.inputKinds:
            o = self.dba.table(kind).get(doc_id=id)
            self.recordAccess(self.searchStore, kind, o.doc_id)
            return o
        else:
            logging.error(
                "attempt to getById unlisted inputKind {0}".format(kind))
            return None


class ModelAccess(object):
    '''Access models in the database.'''

    def __init__(self, database, schemaRepo, contextObj):
        '''Initialize context but don't enable it.'''
        self.dbToUse = database
        self.context = ModelAccessContext(database, schemaRepo, contextObj)
        self.dba = None

    def __enter__(self):
        '''Set up context.'''
        self.dba = self.dbToUse
        self.context.reset()
        return self

    def __exit__(self, etype, value, traceback):
        '''Record context activity in database.'''
        self.context.finalize()
        self.dba = None

    def insert(self, kind, model, traceInputs=None):
        '''
        Insert a model.
        :param kind: the model kind.
        :param model: the model.
        :param traceInputs: list of input model tuples (kind, id).
        :return: the database doc_id number of the new record.
        '''
        id = self.context.insert(kind, model)
        if traceInputs is not None:
            self.trace(kind, id, traceInputs)
        return id

    def setSingleton(self, kind, model, traceInputs=None):
        '''
        Insert a single record, replacing any existing record.
        :param kind: the model kind.
        :param model: the model.
        :param traceInputs: list of input model tuples (kind, id).
        :return: the database doc_id number of the new record.
        '''
        id = self.context.setSingleton(kind, model)
        if traceInputs is not None:
            self.trace(kind, id, traceInputs)
        return id

    def search(self, kind, q):
        '''
        Query within a model kind.
        :param kind: the model kind.
        :param q: the Query.
        :return: list of all models which match the Query.
        '''
        return self.context.search(kind, q)

    def getByKind(self, kind):
        '''
        Get a list of all models of the specified kind.
        :param kind: the model kind.
        :return: list of all models of the specified kind.
        '''
        return self.context.getByKind(kind)

    def getById(self, kind, id):
        '''
        Get a single model of the specified kind and id number.
        :param kind: the model kind.
        :param id: the model doc_id number.
        :return: the specified model or None.
        '''
        return self.context.getById(kind, id)

    def getSingleton(self, kind):
        '''
        Get a single model of the specified kind.
        :param kind: the model kind.
        :return: the specified model or None.
        '''
        return self.context.getSingleton(kind)

    def trace(self, kind, id, traceInputs):
        '''
        Insert trace info.
        :param kind: the model kind.
        :param id: the model ID.
        :param traceInputs: list of input model tuples (kind, id).
        '''
        traceKind = 'fashion.core.trace'
        if traceKind not in self.context.properties.outputKinds:
            logging.error(
                "{0} not in outputKinds of {1}, no trace recorded".format(
                    traceKind, self.context.properties.name))
            return None
    
        traceModel = {
            "kind": kind,
            "id": id,
            "name": self.context.properties.name,
            "inputs": traceInputs
        }
        return self.insert(traceKind, traceModel)

    def generate(self, model, template, targetFile, templateDict={}, projRoot=None, traceInputs=None):
        '''
        Write a generation model for a single file.
        model is the model object to use.
        templateDict
        targetFile is relative to project directory.
        projRoot overrides the project directory.
        :param traceInputs: list of input model tuples (kind, id).
        '''
        genModel = {'model': model,
                    'template': template,
                    'targetFile': targetFile,
                    'templatePath': self.context.properties.templatePath,
                    'templateDict': templateDict,
                    'producer': self.context.properties.name}
        if projRoot is not None:
            genModel["projRoot"] = projRoot
        kind = 'fashion.core.generate.jinja2.spec'
        return self.insert(kind, genModel, traceInputs=traceInputs)
