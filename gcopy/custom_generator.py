# -*- coding: utf-8 -*- 
"""
License:

MIT License

Copyright (c) 2025 Benj1bear

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

------------------------------------------------------------------------------------

In order to make this module as backwards compatible as possible 
some of the functions used will be written out manually and a 
preprocessor or otherwise condition statemnt will go over what 
changes will be made if any

Backwards compatibility notes of relevance at the moment:

For python 2:

 - classes are not automatically inherited from object
   and therefore you have to do this explicitly
 
 - you need to add a comment specifying an encoding at 
   the the first line of the file

 - range returns a list (use xrange instead)

 - type annotations and the typing module were introduced in python 3.5

 - f-strings were introduced in python 3.6 (use i.e. "%s" % ... instead)
"""

from types import FunctionType
from inspect import getsource,currentframe
import ctypes
from copy import deepcopy,copy
from sys import version_info

## python 2 compatibility ##
if version_info < (3,):
    range = xrange

## this needs to be checked ##
class Send(object):
    """
    Special class specifically used in combination with Generator
    to signal where and what to send
    
    Note: Send should only be used after a yield statement and not
    anywhere else. If used elsewhere or no variable has been sent 
    it will have no effect conceptually.
    """
    def __init__(self,ID):
        if not ID.isalnum():
            raise ValueError("ID must be alpha numeric e.g. ID.isalnum() should return True")
        self.ID=ID

    def __repr__(self):
        return "Send('%s')" % self.ID

def collect_string(line):
    """collects a string from a string"""
    if line[0]!="'" or line[0]!='"':
        raise ValueError("'Send' must be given exactly one arguement of type 'str'")
    string=""
    reference_char=line[0]
    line=iter(line)
    for char in line:
        string+=char
        if char=="\\":
            next(line)
            continue
        if char==reference_char:
            break
    return string

def get_indent(line):
    """Gets the number of spaces used in an indentation"""
    count=0
    for char in line:
        if char!=" ":
            break
        count+=1
    return count

def skip(iter_val,n):
    """Skips the next n iterations in a for loop"""
    for _ in range(n):
        next(iter_val)

## Note: line.startswith("except") will need to put a try statement in front (if it's not there e.g. is less than the minimum indent) ##
## match case default was introduced in python 3.10
if version_info < (3,10):
    def is_alternative_statement(line):
        return line.startswith("elif") or line.startswith("else")
else:
    def is_alternative_statement(line):
        return line.startswith("elif") or line.startswith("else") or line.startswith("case") or line.startswith("default")
is_alternative_statement.__doc__="Checks if a line is an alternative statement"

def extract_iter(line):
    """
    Extracts the iterator from a for loop
    
    e.g. we extract the second ... in:
    for ... in ...:
    """
    # 1. get the length of the ids on the left hand side of the "in" keyword
    ID=""
    for index,char in enumerate(line):
        if char.isalphnum():
            ID+=char
            if ID=="in":
                break
        else:
            ID=""
    # 2. collect everything on the right hand side of the "in" keyword
    # 3. remove the end colon
    ## +1 for 0 based indexing, +1 for whitespace after ##
    return line[index+2:][:-1]

## need to handle continue and break within loop (may need to edit or combine with Generator._loop_adjust) ##
## continue - stop recording lines
## break - skip this and carry on make sure
## we need to deal with nested loop on this one
def control_flow_adjust(lines):
    """
    removes unreachable control flow blocks that 
    will get in the way of the generators state

    Note: it assumes that the line is cleaned,
    in particular, that it starts with an 
    indentation of 4
    """
    init_min=get_indent(lines[0])
    if init_min == 4:
        return lines
    alternative,new_lines=False,[]
    current_min=init_min
    for line in lines: ## is having no lines possible? This would raise an error ##
        temp=get_indent(line)
        ## skip over all alternative statements until it's not an alternative statement ##
        if alternative and temp > current_min:
            continue
        elif temp == current_min:
            alternative=is_alternative_statement(line[temp:])
        elif temp < current_min:
            current_min=temp
            ## check for changes ##
            temp_line=line[temp:]
            if temp_line.startswith("except"):
                new_lines=[" "*temp+"try:"]+new_lines+[line]
                continue
            alternative=is_alternative_statement(temp_line)
        if alternative:
            continue
        ## add the line (adjust if indentation is not 4) ##
        if current_min != 4:
            new_lines+=[line[init_min-4:]] ## -4 adjusts the initial block to an indentation of 4 ##
        else:
            new_lines+=[line]
    return new_lines

"""
TODO:
1. fix the control flow adjusters - continue + break for control_flow_adjust
2. check whitespace, linenos, attrs, e.g. the smaller details to clean up
3. try to handle sends with more flexibility for the user e.g. x=yield ... or x=yield from ...
4. format errors
5. figure out how gi_running and gi_suspended are actually supposed to be set
6. write tests
"""
class Generator(object):
    """
    Converts a generator function into a generator 
    function that is copyable (e.g. shallow and deepcopy) 
    and potentially pickle-able
    
    This should be very portable or at least closely so across 
    python implementations ideally.
    
    The dependencies for this to work only requires that you 
    can retrieve your functions source code as a string via
    inspect.getsource.

    How it works:
    
    Basically we emulate the generator process by converting
    it into an on the fly evaluation iterable thus enabling 
    it to be easily copied (Note: deepcopying assumes the
    local variables in the frame can also be copied so if
    you happen to be using a function generator within 
    another function generator then make sure that all
    function generators (past one iteration) are of the 
    Generator type)

    Note: If wanting to use generator expressions i.e.:
    
    (i for i in range(3))
    
    then you can pass it in as a string:
    
    Generator("(i for i in range(3))")
    
    otherwise you could also do something similar to the
    name function in my_pack.name to get the source code
    if desired.
    """

    def _custom_adjustment(self,line,lineno):
        """
        It does the following to the source lines:

        1. replace all lines that start with yields with returns to start with
        2. make sure the generator is closed on regular returns
        3. save the iterator from the for loops replacing with a nonlocal variation
        4. tend to all yield from ... with the same for loop variation
        """
        number_of_indents=get_indent(line)
        if self._skip_indent <= number_of_indents: ## skips if greater to avoid definitions ##
            indent=" "*number_of_indents
            temp_line=line[number_of_indents:]
            if temp_line.startswith("def ") or temp_line.startswith("async def ") or temp_line.startswith("class ") or temp_line.startswith("async class "):
                self._skip_indent=number_of_indents
            else:
                self._skip_indent=0
                if temp_line.startswith("yield "):
                    return [indent+"return"+temp_line[5:]] ## 5 to retain the whitespace ##
                elif temp_line.startswith("yield from "):
                    return [indent+"currentframe().f_back.f_locals['.yieldfrom']="+temp_line[11:],
                            indent+"for currentframe().f_back.f_locals['.i'] in currentframe().f_back.f_locals['.yieldfrom']:",
                            indent+"    return currentframe().f_back.f_locals['.i']"]
                elif temp_line.startswith("for "):
                    self.jump_positions+=[(lineno,None)]
                    self._jump_stack+=[(number_of_indents,len(self.jump_positions)-1)]
                    return [indent+"currentframe().f_back.f_locals['.iter']=iter(%s)" % extract_iter(temp_line[4:]),
                            indent+"for i in currentframe().f_back.f_locals['.iter']:"]
                elif temp_line.startswith("while "):
                    self.jump_positions+=[(lineno,None)]
                    self._jump_stack+=[(number_of_indents,len(self.jump_positions)-1)]
                elif temp_line.startswith("return "):
                    ## close the generator then return ##
                    [indent+"currentframe().f_back.f_locals['self'].close()",line]
        return [line]

    def _clean_source_lines(self,source):
        """
        source: str

        returns source_lines: list[str],return_linenos: list[int]

        1. fixes any indentation issues (when ';' is used) and skips empty lines
        2. split on "\n", ";", and ":"
        3. join up the line continuations i.e. "\ ... " will be skipped
        
        additionally, custom_adjustment will be called on each line formation as well
        """
        ## setup source as an iterator and making sure the first indentation's correct ##
        source=iter(source[get_indent(source):])
        line,lines,backslash,instring,indented,space=" "*4,[],False,False,False,0
        ## enumerate since I want the loop to use an iterator but the 
        ## index is needed to retain it for when it's used on get_indent
        for index,char in enumerate(source):
            ## skip strings ##
            if char=="'" or char=='"' and not backslash:
                instring=(instring + 1) % 2
                line+=char
            elif instring:
                ## keep track of backslash ##
                backslash=(char=="\\")
                line+=char
            ## makes the line singly spaced while retaining the indentation ##
            elif char==" ":
                if indented:
                    if space+1!=index:
                        line+=char
                else:
                    line+=char
                    if space+1!=index:
                        indented=True
                space=index
            ## join everything after the line continuation until the next \n or ; ##
            elif char=="\\":
                skip(source,get_indent(source[index+1:])) ## +1 since index: is inclusive ##
            ## create new line ##
            elif char in "\n;:":
                if char==":":
                    line+=char
                if not line.isspace(): ## empty lines are possible ##
                    reference_indent=get_indent(line)
                    while reference_indent == self._jump_stack[-1][0]:
                        pos=self._jump_stack.pop()
                        reference_indent=pos[0]
                        self.jump_positions[pos[1]][1]=len(lines)+1
                    lines+=self._custom_adjustment(line)
                if char in ":;":
                    line=" "*4
                    skip(source,get_indent(source[index+1:]))
                else:
                    line=""
            else:
                line+=char
        if self._jump_stack:
            ## in case you get a for loop at the end ##
            reference_indent=get_indent(line)
            while reference_indent == self._jump_stack[-1][0]:
                self.jump_positions[self._jump_stack.pop()[1]][1]=len(lines)+1
        return lines

    def _set_reciever(self,lines):
        """sets the reciever of the generator"""
        if self.gi_running:
            line=" ".join(lines[0].strip().split()) # .split() followed by .join ensures the spaces are the same
            # as long as it's 'Send(' and Send is Send e.g. locally or globally defined and is correct
            if line[:5]=='Send(' and (self.gi_frame.f_locals.get("Send",None)==Send or globals().get("Send",None)==Send):
                return collect_string(line[11:])

    def _loop_adjust(self,lines):
        """
        adjusts source code about control flow statements
        so that it can be used in a single directional flow
        as the generators states
        """
        for pos in self.jump_positions: ## importantly we go from start to finish to capture nesting loops ##
            if self.lineno < pos[0]:
                return control_flow_adjust(lines)
            elif self.lineno < pos[1]:
                return control_flow_adjust(lines[:pos[1]]) + self._source_lines[pos[0]:]
        return control_flow_adjust(lines)

    def _create_state(self):
        """
        creates a section of modified source code to be used in a 
        function to act as a generators state

        The approach is as follows:

        Use the entire source code, reducing from the last lineno.
        Adjust the current source code reduction further out of
        control flow statements, loops, etc. then set the adjusted 
        source code as the generators state
        """
        self.lineno+=self.gi_frame.f_lineno-self.init_len
        ## extract the code section ##
        lines=self._source_lines[self.lineno:]
        ## used on .send (shouldn't be modified by the user)
        self.reciever=self._set_reciever(lines)
        self.state="\n".join(self._loop_adjust(lines))

    init="""
    locals().update(f_locals)
    frame=currentframe()
    frame.f_back.f_locals['self'].gi_frame=frame
    ctypes.pythonapi.PyFrame_LocalsToFast(ctypes.py_object(frame.f_back), ctypes.c_int(0))
"""
    init_len=init.count("\n")+1

    def init_states(self):
        """
        Initializes the state generation

        It goes line by line to find the 
        lines that have the yield statements
        """
        while self.state:
            try:
                yield self._create_state()
            except StopIteration:
                break

    class frame(object):
        """acts as the initial FrameType"""
        f_locals={}
        f_lineno=0

    def __init__(self,FUNC):
        """
        Takes in a function or its source code as the first arguement

        Otherwise it takes a dictionary of attributes as the keyword arguements
        """
        if isinstance(FUNC,dict):
            for attr in ("source","gi_code","gi_frame","gi_running","gi_suspended","gi_yieldfrom",
                         "_source_lines","lineno","reciever","state"):
                setattr(self,attr,FUNC[attr])
        else:
            ## getsource does work for expressions but it's got no col_offset which is not useful ##
            ## but it may still work with some adjustments (maybe) ##
            if isinstance(FUNC,str): ## from source code ##
                self.source=FUNC
                self.gi_code=compile(FUNC,"","eval")
                self.gi_frame=self.frame()
            elif isinstance(FUNC,FunctionType): ## a generator function ##
                self.source=getsource(FUNC)
                self.gi_code=FUNC.__code__
                self.gi_frame=self.frame()
            else: ## an initialized generator ##
                self.source=getsource(FUNC.gi_code)
                self.gi_code=FUNC.gi_code
                self.gi_frame=FUNC.gi_frame
            ## for loop adjustments ##
            self.jump_positions=[]
            self._jump_stack=[]
            self._skip_indent=0
            ## make sure the source code is standardized and usable by this generator ##
            self._source_lines=self._clean_source_lines()
            ## are not used by this generator (was only for formatting source code) ##
            del self._jump_stack,self._skip_indent
            ## create the states ##
            ## define the state related variables in __init__ to allow the state generator ##
            ## to be independent i.e. when initializing via **attrs ##
            self.gi_running=False
            self.gi_suspended=False
            ## indicates what iterable is being yield from when the yield is a yield from (introduced in python version 3.3) ##
            self.gi_yieldfrom=None
            self.lineno=0 ## the current line number relative to self._source_lines ##
            self.gi_frame.f_lineno=self.init_len # is this necessary??
        self.state_generator=self.init_states()

    def __len__(self):
        """
        Gets the number of states for generators with yield 
        statements indented exactly 4 spaces.

        In general, you shouldn't be able to get the length
        of a generator function, but if it's very predictably
        defined then you can.
        """
        def number_of_yields():
            """Gets the number of yields that are indented exactly 4 spaces"""
            for line in self._source_lines:
                indents=get_indent(line)
                temp=line[indents:]
                if temp.startswith("yield") and not temp.startswith("yield from"):
                    if indents > 4:
                        raise TypeError("__len__ is only available where all yield statements are indented exactly 4 spaces")
                    yield 1
        return sum(number_of_yields())

    def __iter__(self):
        """Converts the generator function into an iterable"""
        while True:
            try:
                yield next(self)
            except StopIteration:
                break

    def __next__(self):
        """
        1. change the state
        2. return the value
        """
        # set the next state and setup the function
        next(self.state_generator) ## it will raise a StopIteration for us
        # if not set already
        if not self.gi_running:
            self.gi_running=True ## apparently i.e. yield from range(...) changes this to False ##
            self.gi_suspended=True
        ## update with the new state and get the frame ##
        exec("def next_state(f_locals):"+self.init+self.state,globals(),locals())
        # get the locals dict, update the line position, and return the result
        try:
            return locals()["next_state"](self.gi_frame.f_locals)
        except Exception as e: ## we should format the exception as it normally would be formmated ideally
            self._format_exception(e)

    def send(self,arg):
        """
        Send takes exactly one arguement 'arg' that 
        is sent to the functions yield variable
        """
        if not self.gi_running:
            raise TypeError("can't send non-None value to a just-started generator")
        if self.reciever:
            self.gi_frame.f_locals()[self.reciever]=arg
        return next(self)

    def close(self):
        """Creates a simple empty generator"""
        self.state_generator=(None for i in ())
        self.gi_frame=None
        self.gi_running=False
        self.gi_suspended=False

    def throw(self,exception):
        """Throws an error at the current line of execution in the function"""
        # get the current position (should be recorded and updated after every execution)
        self._format_exception(exception)

    def _format_exception(self,exception):
        """Raises an exception from the last line in the current state e.g. only from what has been"""
        raise exception

    def _copier(self,FUNC):
        """copying will create a new generator object but the copier will determine it's depth"""
        attrs=dict(
            zip(
                ((attr,FUNC(getattr(self,attr))) for attr in \
                        ("source","_source_lines","gi_code","gi_frame","gi_running",
                         "gi_suspended","gi_yieldfrom","state","state_index","lineno",
                         "end_lineno","reciever","state_generator"))
                )
            )
        return Generator(None,**attrs)
    ## for copying ##
    def __copy__(self):
        return self._copier(copy)
    def __deepcopy__(self,memo):
        return self._copier(deepcopy)
    ## for pickling ##
    def __getstate__(self):
        """Serializing pickle (what object you want serialized)"""
        _attrs=("source","pos","_states","gi_code","gi_frame","gi_running",
                "gi_suspended","gi_yieldfrom","state_generator","state","reciever")
        return dict(zip(_attrs,(getattr(self,attr) for attr in _attrs)))

    def __setstate__(self,state):
        """Deserializing pickle (returns an instance of the object with state)"""
        Generator(None,**state)

## add the type annotations if the version is 3.5 or higher ##
if (3,5) <= version_info[:3]:
    from typing import Callable,Any,NoReturn,Iterable
    import types
    ## Send
    Send.__init__.__annotations__={"ID":str,"return":None}
    Send.__repr__.__annotations__={"return":str}
    ## utility functions
    collect_string.__annotations__={"line":str,"return":str}
    get_indent.__annotations__={"line":str,"return":int}
    skip.__annotations__={"iter_val":Iterable,"n":int,"return":None}
    is_alternative_statement.__annotations__={"line":str,"return":bool}
    extract_iter.__annotations__={"line":str,"return":str}
    control_flow_adjust.__annotations__={"lines":list[str],"return":list[str]}
    ## Generator
    Generator._custom_adjustment.__annotations__={"return":None}
    Generator._clean_source_lines.__annotations__={"return":None}
    Generator._loop_adjust.__annotations__={"lines":list[str],"return":str}
    Generator._set_reciever.__annotations__={"lines":list[str],"return":None}
    Generator._create_state.__annotations__={"lineno":int,"return":None}
    Generator.init_states.__annotations__={"return":None}
    Generator.__init__.__annotations__={"FUNC":Callable|str|types.Generator,"return":None}
    Generator.__len__.__annotations__={"return":int}
    Generator.__iter__.__annotations__={"return":iter}
    Generator.__next__.__annotations__={"return":Any}
    Generator.send.__annotations__={"arg":Any,"return":Any}
    Generator.close.__annotations__={"return":None}
    Generator.throw.__annotations__={"exception":Exception,"return":None}
    Generator._format_exception.__annotations__={"exception":Exception,"return":NoReturn}
    Generator._copier.__annotations__={"FUNC":Callable,"return":Generator}
    Generator.__copy__.__annotations__={"return":Generator}
    Generator.__deepcopy__.__annotations__={"memo":dict,"return":Generator}
    Generator.__getstate__.__annotations__={"return":dict}
    Generator.__setstate__.__annotations__={"state":dict,"return":None}
