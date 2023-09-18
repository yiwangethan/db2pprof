import contextlib
import dataclasses
import io
import struct
import sys
from pathlib import Path

import json
import pytest
from tarball import extracted

from _test_util import assert_good_traversal, dump_to_string, yaml
from metadb import Context, MetaDB, _Flex
from profiledb import ProfileDB
from cctdb import ContextDB

import profile_pb2 as pb
import pprint


'''
profile.db format:
    0: 1000000000.0  # for point  #0
    1: 1000000000.0 # for function  #1
    2: 1000000000.0 # for lex_aware  #2
    3: 1000000000.0 # for execution  #3

Usage: got.profile_infos.profiles[0].values[0].get(3)
'''

'''
meta.db:
usage: got.context.entry_points[0].children
'''



def string_table_build(string_table, module_range, funcname_range, filepath_range):
    tmp_id = 5
    
    # Write modules into string table
    for mod in meta_db.modules.modules:
        module_range.append(tmp_id)
        string_table.append(mod.path)
        tmp_id += 1
        
    # Write functions into sting table
    for funcname in meta_db.functions.functions:
        funcname_range.append(tmp_id)
        string_table.append(funcname.name)
        tmp_id += 1
    
    # Write souce files into string table
    for filepath in meta_db.files.files:
        filepath_range.append(tmp_id)
        string_table.append(filepath.path)
        tmp_id += 1

    return string_table, module_range, funcname_range, filepath_range
    

def write_valuetype(all_valuetypes):
    valuetype1 = pb.ValueType()
    valuetype1.type = 1
    valuetype1.unit = 2
    
    valuetype2 = pb.ValueType()
    valuetype2.type = 3
    valuetype2.unit = 4
    
    all_valuetypes.append(valuetype1)
    all_valuetypes.append(valuetype2)
    
    return all_valuetypes



def write_functions(all_functions, funcname_range, meta_db):
    id = 1 # id start from 1
    for range_id in range(len(funcname_range)):
        function = pb.Function()
        
        # Unique id
        function.id = id
        
        # Name of the function, in human-readable form if available.
        funcname_id = funcname_range[range_id]
        function.name = funcname_id # Index into string table
        
        # Name of the function, as identified by the system.
        # For instance, it can be a C++ mangled name.
        function.system_name = funcname_id # No system name found, instead I use function name.
        
        # # Source file containing the function.
        # filename = meta_db.functions.functions[range_id].file.path
        # function.filename = 
        
        # Line number in source file.
        function.start_line = meta_db.functions.functions[range_id].line
        
        all_functions.append(function)
        id += 1
    return all_functions


# One mapping object per source file
def write_mapping(all_mappings, filepath_range):
    id = 1
    for range_id in range(len(filepath_range)):
        mapping = pb.Mapping()
        mapping.id = id
        mapping.memory_start = 0 # Cannot find info, use 0 instead
        mapping.memory_limit = 0 # Cannot find info, use 0 instead
        mapping.file_offset = 0 # Cannot find info, use 0 instead
        mapping.filename = filepath_range[range_id]
        
        
        all_mappings.append(mapping)
        id += 1
    
    return all_mappings
    

# One location per function
def write_location(all_locations, funcname_range, meta_db, function_to_path, string_table, filepath_range):
    id = 1
    # print(len(funcname_range))
    for range_id in range(len(funcname_range)):
        location = pb.Location()
        location.id = id
        
        funcname = string_table[funcname_range[range_id]]
        filepath = function_to_path.get(funcname)
        tmpid = 0
        for i in range(len(filepath_range)):
            if string_table[filepath_range[i]] == filepath:
                tmpid = i

        location.mapping_id = tmpid
        location.address = 0
        
        # Line info
        line = pb.Line()
        # line.function_id = funcname_range[range_id]
        funcid = range_id + 1
        line.function_id = funcid
        line.line = meta_db.functions.functions[range_id].line
        
        # if id == 25:
        #     print(id)
        #     print(funcname_range[range_id])
        #     print(meta_db.functions.functions[range_id])
        
        location.line.append(line)
        
        all_locations.append(location)
        id += 1
    
    return all_locations


def has_children(node, function_to_context):
    if hasattr(node, 'children'):
        for child in node.children:
            ctx_id = child.ctx_id
            if child.function is not None:
                func_name = child.function.name
                function_to_context[func_name] = ctx_id
            # if child.function is None:
            #     print("None")
            # if ctx_id in profile_db.profile_infos.profiles[0].values:
            #     print(profile_db.profile_infos.profiles[0].values[ctx_id].get(3))
            has_children(child, function_to_context)


def parse_functions_to_ctxids(function_to_context):
    for child in meta_db.context.entry_points[0].children:
        ctx_id = child.ctx_id
        # print(child.function.name)
        func_name = child.function.name
        function_to_context[func_name] = ctx_id
        # if ctx_id in profile_db.profile_infos.profiles[0].values:
        #     print(profile_db.profile_infos.profiles[0].values[ctx_id].get(3))
        has_children(child, function_to_context)
    
    return function_to_context



def func_to_path(function_to_path, meta_db):
    for func in meta_db.functions.functions:
        function_to_path[func.name] = func.file.path
           
    return function_to_path


# One sample object per function
def write_sample(all_samples, string_table, funcname_range, function_to_context, profile_db):
    i = 1
    for range_id in range(len(funcname_range)):
        sample = pb.Sample()
        sample.location_id.append(i)
        i += 1
    
        sample.value.append(1)
        func_name_str = string_table[funcname_range[range_id]]
        ctx_id = function_to_context.get(func_name_str)
        perfvalue = profile_db.profile_infos.profiles[0].values[ctx_id].get(3)
        sample.value.append(int(perfvalue*1000000000))
        
        all_samples.append(sample)
    
    return all_samples
    


if __name__ == "__main__":
    with open("meta.db", "rb") as metaf, open("profile.db", "rb") as profilef, open("cct.db", "rb") as cctf:
        meta_db = MetaDB.from_file(metaf)
        profile_db = ProfileDB.from_file(profilef)
        cct_db = ContextDB.from_file(cctf)
    
    all_samples = []
    all_mappings = []
    all_locations = []
    all_functions = []
    all_valuetypes = []
    

    function_to_context = {}
    function_to_path = {}
    
    function_to_path = func_to_path(function_to_path, meta_db)
    
    string_table = ["", "samples", "count", "cpu", "nanoseconds"]
    module_range = []
    funcname_range = []
    filepath_range = []

    string_table, module_range, funcname_range, filepath_range = string_table_build(string_table, module_range, funcname_range, filepath_range)
    function_to_context = parse_functions_to_ctxids(function_to_context)
    # print(function_to_context)
    
    all_functions = write_functions(all_functions, funcname_range, meta_db)
    all_samples = write_sample(all_samples, string_table, funcname_range, function_to_context, profile_db)
    all_mappings = write_mapping(all_mappings, filepath_range)
    all_locations = write_location(all_locations, funcname_range, meta_db, function_to_path, string_table, filepath_range)
    
    all_valuetypes = write_valuetype(all_valuetypes)
    
    with open("db2pprof.pb", "wb") as dbf:
        profile = pb.Profile()
        profile.sample.extend(all_samples)
        profile.mapping.extend(all_mappings)
        profile.location.extend(all_locations)
        profile.function.extend(all_functions)
        profile.sample_type.extend(all_valuetypes)
        profile.string_table.extend(string_table)
        
        dbf.write(profile.SerializeToString())
        
        # for sample in all_samples:
        #     dbf.write(sample.SerializeToString())
        
        # for mapping in all_mappings:
        #     dbf.write(mapping.SerializeToString())
        
        # for location in all_locations:
        #     dbf.write(location.SerializeToString())
            
        # for valuetype in all_valuetypes:
        #     dbf.write(valuetype.SerializeToString())
        
        # for function in all_functions:
        #     dbf.write(function.SerializeToString())
    






# Pprof valuetype format example:
# 
# SampleType: []*ValueType{
# 		{Type: "samples", Unit: "count"},
# 		{Type: "cpu", Unit: "milliseconds"},
# 	}

# DurationNanos: 10e9,
# 	SampleType: []*ValueType{
# 		{Type: "cpu", Unit: "cycles"},
# 		{Type: "object", Unit: "count"},
# 	},
# 

    
# Pprof sample format example:
# 
# Sample: []*Sample{
# 		{
# 			Location: []*Location{cpuL[0]},
# 			Value:    []int64{1000, 1000},
# 			Label: map[string][]string{
# 				"key1": {"tag1"},
# 				"key2": {"tag1"},
# 			},
# 		},    
# def write_sample():
#     tmpid = 1
    
#     # The ids recorded here correspond to a Profile.location.id.
#     # The leaf is at location_id[0].
#     sample.location_id = location[tmpid]
    
#     # The type and unit of each value is defined by the corresponding
#     # entry in Profile.sample_type. All samples must have the same
#     # number of values, the same as the length of Profile.sample_type.
#     # When aggregating multiple samples into a single sample, the
#     # result has a list of values that is the element-wise sum of the
#     # lists of the originals.
#     sample.value = 
    
#     # label includes additional context for this sample. It can include
#     # things like a thread id, allocation size, etc.
#     sample.label = label[tmpid]


# Pprof label format example:
# 
# Label: map[string][]string{
# 				"key1": {"tag1"},
# 				"key2": {"tag1"},
# 			},
# def write_label():
#     label.key = 



# Pprof mapping format example:
# 
# var cpuM = []*Mapping{
# 	{
# 		ID:              1,
# 		Start:           0x10000,
# 		Limit:           0x40000,
# 		File:            mainBinary,
# 		HasFunctions:    true,
# 		HasFilenames:    true,
# 		HasLineNumbers:  true,
# 		HasInlineFrames: true,
# 	},
# def write_mapping():
#     # tmpid = 1
#     # all_mappings = []
#     # for load_module in meta_db.modules.modules:
#     load_module = meta_db.modules.modules
#     # Unique nonzero id for the mapping.
#     mapping.id = 1
#     mapping.memory_start = 0
#     mapping.memory_limit = 0
#     mapping.offset = 0
#     mapping.file = load_module.
        
#         # all_mappings.append(mapping)
#         # tmpid += 1
        
#     # return all_mappings
    
    
# Pprof location format example:
# 
# var cpuL = []*Location{
# 	{
# 		ID:      1000,
# 		Mapping: cpuM[1],
# 		Address: 0x1000,
# 		Line: []Line{
# 			{Function: cpuF[0], Line: 1},
# 		},
# 	},
# def write_location():
#     all_locations = []
#     tmpid = 1
#     location.id = tmpid
#     location.mapping_id = 
#     location.address = 
#     location.line = line[tmpid]
    

# def write_line():
#     tmpid = 1
#     location.id = tmpid
    
#     location.mapping_id = 
#     # The instruction address for this location, if available.  It
#     # should be within [Mapping.memory_start...Mapping.memory_limit]
#     # for the corresponding mapping. A non-leaf address may be in the
#     # middle of a call instruction. It is up to display tools to find
#     # the beginning of the instruction if necessary.
#     location.address = 
    
    


# def write_function():
#     # all_functions = []
#     tmpid = 1
#     for func in meta_db.functions.functions:

#         func.file_idx = add_to_string_table(func.filename)
#         func.name_idx = add_to_string_table(func.name)
#         func.system_name_idx = add_to_string_table(func.system_name)
        
#         function = pb.Function()
#         # Unique nonzero id for the function.
#         function.id = tmpid
#         # Name of the function, in human-readable form if available.
#         function.name = func.name_idx
#         # Name of the function, as identified by the system.
#         # For instance, it can be a C++ mangled name.
#         function.system_name = func.name
#         # Source file containing the function.
#         function.filename = func.file_idx
#         # Line number in source file.
#         function.start_line = func.line
        
#         # all_functions.append(function)
#         tmpid += 1
        
#     # return all_functions



# # Helper function to add strings to string table and update indices
# def add_to_string_table(s):
#     if s not in string_table:
#         string_table.append(s)
#     # string_table.append(s)    
#     return string_table.index(s)



# string table structure:
# type
# unit
# file name 
# function name
# system name
# 
# 
# 
