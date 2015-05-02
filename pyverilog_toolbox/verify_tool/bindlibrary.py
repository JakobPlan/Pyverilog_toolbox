#-------------------------------------------------------------------------------
# bindlibrary.py
#
# bindlibrary
#
#
# Copyright (C) 2015, Ryosuke Fukatani
# License: Apache 2.0
#-------------------------------------------------------------------------------

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) )

import pyverilog.utils.version
import pyverilog.utils.util as util
from pyverilog.dataflow.dataflow import *
from types import MethodType

class BindLibrary(object):
    """ [CLASSES]
        Library for using dataflow information.
    """

    def __init__(self, binddict, terms):
        def make_scope_dict(terms):
            """ [FUNCTIONS] for getScopeChaindict
            make {string: ScopeChain, ...} from binddict
            """
            return_dict = {}
            for scope in terms.keys():
                return_dict[str(scope)] = scope
            return return_dict

        self._binddict = binddict
        self._terms = terms
        self.scope_dict = make_scope_dict(terms)
        self.cache = {}
        self.gnb_cache = {}

    def dfx_memoize(f):
        def helper(self, target_tree, tree_list, bit, dftype):
            if dftype == pyverilog.dataflow.dataflow.DFTerminal:
                if (target_tree,bit) not in self.cache:
                    self.cache[(target_tree,bit)] = f(self, target_tree, set([]), bit, dftype)
                return tree_list.union(self.cache[(target_tree,bit)])
            else:
                return f(self, target_tree, tree_list,bit,dftype)
        return helper

    @dfx_memoize
    def extract_all_dfxxx(self, target_tree, tree_list, bit, dftype):
        """[FUNCTIONS]
        return set of DFXXX
        target_tree:DF***
        tree_list:{(type, DF***, bit),(type, DF***, bit),...}
        bit: signal bit pointer
        dftype: DFOperator or DFIntConst or ,...
        """
        if dftype == pyverilog.dataflow.dataflow.DFTerminal and isinstance(target_tree, pyverilog.dataflow.dataflow.DFTerminal):
            target_scope = self.get_scope(target_tree)
            if target_scope in self._binddict.keys():
                target_bind, target_term_lsb = self.get_next_bind(target_scope, bit)
                if not target_bind.isCombination():
                    tree_list.add((target_tree, bit + target_term_lsb))
            else:#TOP Input port
                tree_list.add((target_tree, bit + eval_value(self._terms[self.scope_dict[str(target_tree)]].lsb)))
        else:
            if isinstance(target_tree, dftype):
                tree_list.add((target_tree, bit))

        if hasattr(target_tree, "nextnodes"):
            if isinstance(target_tree, pyverilog.dataflow.dataflow.DFConcat):
                now_max_bit = 0
                now_min_bit = 0
                for nextnode in reversed(target_tree.nextnodes):
                    now_max_bit = now_min_bit + self.get_bit_width_from_tree(nextnode) - 1
                    if now_min_bit <= bit <= now_max_bit:
                        tree_list = self.extract_all_dfxxx(nextnode, tree_list, bit - now_min_bit, dftype)
                        break
                    now_min_bit = now_max_bit + 1
            else:
                for nextnode in target_tree.nextnodes:
                    if isinstance(target_tree, pyverilog.dataflow.dataflow.DFBranch) and nextnode == target_tree.condnode:
                        tree_list = self.extract_all_dfxxx(nextnode,tree_list, 0, dftype)
                    else:
                        tree_list = self.extract_all_dfxxx(nextnode,tree_list, bit, dftype)
        elif isinstance(target_tree, pyverilog.dataflow.dataflow.DFBranch):
            tree_list = self.extract_all_dfxxx(target_tree.condnode, tree_list, 0, dftype)
            tree_list = self.extract_all_dfxxx(target_tree.truenode, tree_list, bit, dftype)
            tree_list = self.extract_all_dfxxx(target_tree.falsenode, tree_list, bit, dftype)
        elif isinstance(target_tree, pyverilog.dataflow.dataflow.DFTerminal):
            target_scope = self.get_scope(target_tree)
            if target_scope in self._binddict.keys():
                target_bind, target_term_lsb = self.get_next_bind(target_scope, bit)
                if target_bind.isCombination():
                    tree_list = self.extract_all_dfxxx(target_bind.tree, tree_list, bit, dftype)
        elif isinstance(target_tree, pyverilog.dataflow.dataflow.DFPartselect):
            #ref_bit = eval_value(target_tree.lsb) + bit
            ref_bit = eval_value(target_tree.lsb) + bit - eval_value(self._terms[self.scope_dict[str(target_tree.var)]].lsb)
            tree_list = self.extract_all_dfxxx(target_tree.var, tree_list, ref_bit, dftype)
        return tree_list


    def search_combloop(self, target_tree, bit, start_tree, start_bit, find_cnt=0):
        """[FUNCTIONS]
        target_tree:DF***
        bit: signal bit pointer
        start_tree:DF***
        """
        if (str(target_tree), bit) == (start_tree, start_bit):
            find_cnt += 1
        if find_cnt == 2:
            raise CombLoopException('Combinational loop is found @' + str(start_tree))

        if hasattr(target_tree, "nextnodes"):
            if isinstance(target_tree, pyverilog.dataflow.dataflow.DFConcat):
                now_max_bit = 0
                now_min_bit = 0
                for nextnode in reversed(target_tree.nextnodes):
                    now_max_bit = now_min_bit + self.get_bit_width_from_tree(nextnode) - 1
                    if now_min_bit <= bit <= now_max_bit:
                        self.search_combloop(nextnode, bit - now_min_bit, start_tree, start_bit, find_cnt)
                        break
                    now_min_bit = now_max_bit + 1
            else:
                for nextnode in target_tree.nextnodes:
                    if isinstance(target_tree, pyverilog.dataflow.dataflow.DFBranch) and nextnode == target_tree.condnode:
                        self.search_combloop(nextnode, 0, start_tree, start_bit, find_cnt)
                    else:
                        self.search_combloop(nextnode, bit, start_tree, start_bit, find_cnt)
        elif isinstance(target_tree, pyverilog.dataflow.dataflow.DFBranch):
            self.search_combloop(target_tree.condnode, 0, start_tree, start_bit, find_cnt)
            self.search_combloop(target_tree.truenode, bit, start_tree, start_bit, find_cnt)
            self.search_combloop(target_tree.falsenode, bit, start_tree, start_bit, find_cnt)
        elif isinstance(target_tree, pyverilog.dataflow.dataflow.DFTerminal):
            target_scope = self.get_scope(target_tree)
            if target_scope in self._binddict.keys():
                target_bind, target_term_lsb = self.get_next_bind(target_scope, bit)
                if target_bind.isCombination():
                    self.search_combloop(target_bind.tree, bit, start_tree, start_bit, find_cnt)
        elif isinstance(target_tree, pyverilog.dataflow.dataflow.DFPartselect):
            ref_bit = eval_value(target_tree.lsb) + bit - eval_value(self._terms[self.scope_dict[str(target_tree.var)]].lsb)
            self.search_combloop(target_tree.var, ref_bit, start_tree, start_bit, find_cnt)
        return


    def delete_all_cache(self):
        self.cache = {}
        self.gnb_cache= {}

    def gnb_memoize(f):
        def helper(self,y,z):
            if (y,z) not in self.gnb_cache:
               self.gnb_cache[(y,z)] = f(self,y,z)
            return self.gnb_cache[(y,z)]
        return helper

    @gnb_memoize
    def get_next_bind(self, scope, bit):
        """[FUNCTIONS] get root bind.(mainly use at 'Rename' terminal.)
        """
        if scope in self._binddict.keys():
            target_binds = self._binddict[scope]
            target_bind_index = self.get_bind_index(target_binds, bit + eval_value(self._terms[scope].lsb), self._terms[scope])
            #target_bind_index = self.get_bind_index(target_binds, bit, self._terms[scope])
            target_bind = target_binds[target_bind_index]
            return target_bind, eval_value(self._terms[scope].lsb)
        else:
            return None, self._terms[scope].lsb

    def get_bind_index(self, binds=None, bit=None, term=None, scope=None):
        """[FUNCTIONS] get bind index in that target bit exists.
        """
        if 'Rename' in term.termtype:
            return 0
        else:
            if scope is not None:
                binds = self._binddict[scope]
                term = self._terms[scope]
            for index,bind in enumerate(binds):
                if bind.lsb is None:
                    return 0
                if self.get_bind_lsb(bind) <= bit <= self.get_bind_msb(bind):
                    return index
            else:
                raise IRREGAL_CODE_FORM("unexpected bind @"+binds[0].tostr())


    def get_bit_width_from_tree(self, tree):
        onebit_comb = ('Ulnot','Unot','Eq', 'Ne','Lor','Land','Unand','Uor','Unor','Uxor','Uxnor')
        if isinstance(tree, pyverilog.dataflow.dataflow.DFTerminal):
            term = self._terms[self.get_scope(tree)]
            return eval_value(term.msb)  + 1
        elif isinstance(tree, pyverilog.dataflow.dataflow.DFPartselect):
            return eval_value(tree.msb) - eval_value(tree.lsb) + 1
        elif isinstance(tree, pyverilog.dataflow.dataflow.DFOperator):
            if tree.operator in onebit_comb:
                return 1
            else:
                each_sizes = (self.get_bit_width_from_tree(nextnode) for nextnode in tree.nextnodes)
                return min(each_sizes)
        elif isinstance(tree, pyverilog.dataflow.dataflow.DFIntConst):
            return tree.width()
        elif isinstance(tree, pyverilog.dataflow.dataflow.DFConcat):
            return sum([self.get_bit_width_from_tree(nextnode) for nextnode in tree.nextnodes])
        elif isinstance(tree, pyverilog.dataflow.dataflow.DFEvalValue):
            return tree.width
        else:
            raise IRREGAL_CODE_FORM("unexpected concat node")

    def walk_reg_each_bit(self):
        for tk, tv in sorted(self._terms.items(), key=lambda x:len(x[0])):
            if tk in self._binddict.keys():
                for bvi in self._binddict[tk]:#process for each always block
                    bind_lsb = self.get_bind_lsb(bvi)
                    bind_msb = self.get_bind_msb(bvi)
                    for bit in range(bind_lsb, bind_msb + 1):
                        yield tv, tk, bvi, bit, bind_lsb

    def get_bind_lsb(self, bind):
        if bind.lsb:
            return bind.lsb.value
        else:
            return 0

    def get_bind_msb(self, bind):
        if bind.msb:
            return bind.msb.value
        else:
            return 0

    def get_scope(self, tree):
        name = str(tree)
        if name in self.scope_dict.keys():
            return self.scope_dict[name]
        else:
            return None

class CombLoopException(Exception): pass

class MothernodeSetter(BindLibrary) :
    """[CLASSES]
    set mother node for all nodes.
    need expressly call destructer.
    """
    def __init__(self, bind_library) :
        self._binddict = bind_library._binddict
        self._terms = bind_library._terms
        self.scope_dict = bind_library.scope_dict
        self.cache = bind_library.cache
        self.gnb_cache = bind_library.gnb_cache
        self.disable_dfxxx_eq()

    def __del__(self):
        self.enable_dfxxx_eq()

    def set_mother_node(f):
        def helper(self, target_tree, tree_list, bit, dftype):
            tree_list = f(self, target_tree, tree_list, bit, dftype)
            if tree_list:
                for tree, bit in tree_list:
                    tree.mother_node = target_tree
            return tree_list
        return helper

    @set_mother_node
    def extract_all_dfxxx(self, target_tree, tree_list, bit, dftype):
        return BindLibrary.extract_all_dfxxx(self, target_tree, tree_list, bit, dftype)

    def disable_dfxxx_eq(self):
        """ [FUNCTIONS]
            Chenge df***.__eq__()method to identify each tree.
        """
        DFConstant.__eq__ = MethodType(return_false, None, DFConstant)
        DFEvalValue.__eq__ = MethodType(return_false, None, DFEvalValue)
        DFUndefined.__eq__ = MethodType(return_false, None, DFUndefined)
        DFHighImpedance.__eq__ = MethodType(return_false, None, DFHighImpedance)
        DFTerminal.__eq__ = MethodType(return_false, None, DFTerminal)
        DFBranch.__eq__ = MethodType(return_false, None, DFBranch)
        DFOperator.__eq__ = MethodType(return_false, None, DFOperator)
        DFPartselect.__eq__ = MethodType(return_false, None, DFPartselect)
        DFPointer.__eq__ = MethodType(return_false, None, DFPointer)
        DFConcat.__eq__ = MethodType(return_false, None, DFConcat)
        #DFDelay.__eq__ = MethodType(return_false, None, DFDelay)
        #DFSyscall.__eq__ = MethodType(return_false, None, DFSyscall)

    def enable_dfxxx_eq(self):
        DFConstant.__eq__ = MethodType(DFConstant_eq_org, None, DFConstant)
        DFEvalValue.__eq__ = MethodType(DFEvalValue_eq_org, None, DFEvalValue)
        DFUndefined.__eq__ = MethodType(DFUndefined_eq_org, None, DFUndefined)
        DFHighImpedance.__eq__ = MethodType(DFHighImpedance_eq_org, None, DFHighImpedance)
        DFTerminal.__eq__ = MethodType(DFTerminal_eq_org, None, DFTerminal)
        DFBranch.__eq__ = MethodType(DFBranch_eq_org, None, DFBranch)
        DFOperator.__eq__ = MethodType(DFOperator_eq_org, None, DFOperator)
        DFPartselect.__eq__ = MethodType(DFPartselect_eq_org, None, DFPartselect)
        DFPointer.__eq__ = MethodType(DFPointer_eq_org, None, DFPointer)
        DFConcat.__eq__ = MethodType(DFConcat_eq_org, None, DFConcat)

def return_false(self, other):
    return False

def DFConstant_eq_org(self, other):
    if type(self) != type(other): return False
    return self.value == other.value

def DFEvalValue_eq_org(self, other):
    if type(self) != type(other): return False
    return self.value == other.value and self.width == other.width and self.isfloat == other.isfloat and self.isstring == other.isstring

def DFUndefined_eq_org(self, other):
    if type(self) != type(other): return False
    return self.width == other.width

def DFHighImpedance_eq_org(self, other):
    if type(self) != type(other): return False
    return self.width == other.width

def DFTerminal_eq_org(self, other):
    if type(self) != type(other): return False
    return self.name == other.name

def DFBranch_eq_org(self, other):
    if type(self) != type(other): return False
    return self.condnode == other.condnode and self.truenode == other.truenode and self.falsenode == other.falsenode

def DFOperator_eq_org(self, other):
    if type(self) != type(other): return False
    return self.operator == other.operator and self.nextnodes == other.nextnodes

def DFPartselect_eq_org(self, other):
    if type(self) != type(other): return False
    return self.var == other.var and self.msb == other.msb and self.lsb == other.lsb

def DFPointer_eq_org(self, other):
    if type(self) != type(other): return False
    return self.var == other.var and self.ptr == other.ptr

def DFConcat_eq_org(self, other):
    if type(self) != type(other): return False
    return self.nextnodes == other.nextnodes

def eval_value(tree):
    if isinstance(tree, pyverilog.dataflow.dataflow.DFOperator):
        for nextnode in self.nextnodes:
            assert(isinstance(nextnode, pyverilog.dataflow.dataflow.DFEvalValue)
                or isinstance(nextnode, pyverilog.dataflow.dataflow.DFIntConst)
                or isinstance(nextnode, pyverilog.dataflow.dataflow.DFOperator)
                or isinstance(nextnode, pyverilog.dataflow.dataflow.DFTerminal))
        if self.operator == 'Plus':
            return eval_value(nextnodes[0]) + eval_value(nextnodes[1])
        elif self.operator == 'Minus':
            return eval_value(nextnodes[0]) - eval_value(nextnodes[1])
        elif self.operator == 'Times':
            return eval_value(nextnodes[0]) * eval_value(nextnodes[1])
        else:#unimplemented
            raise Exception
    elif isinstance(tree, pyverilog.dataflow.dataflow.DFTerminal):
        if self.get_scope(scopedict) in binddict.keys():
            return binddict[self.get_scope(scopedict)][0].tree.eval()
        else:
            raise verror.ImplementationError()
    elif isinstance(tree, pyverilog.dataflow.dataflow.DFIntConst):
        return tree.eval()
    elif isinstance(tree, pyverilog.dataflow.dataflow.DFEvalValue):
        return tree.value


