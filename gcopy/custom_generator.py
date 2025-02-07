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

reference for versions not available on the 
cpython github repo or as an alternative for 
where documentation is lacking: https://hg.python.org/cpython/file/2.2

(2.2 since this is when generators were introduced)

For python 2:

 - classes are not automatically inherited from object
   and therefore you have to do this explicitly
 
 - you need to add a comment specifying an encoding at 
   the the first line of the file

 - range returns a list (use xrange instead)

 - type annotations and the typing module were introduced in python 3.5

 - f-strings were introduced in python 3.6 (use i.e. "%s" % ... instead)
 
 - builtin function 'next' was introduced in 2.6

 - dedent from textwrap module and get_history_item were introduced in 2.3

 - before version 3.0 __bool__ was __nonzero__

 - dis.get_instructions was introduced in 3.4

 - CodeType.co_positions was introduced in 3.11

 - Coroutines were introduced in 3.5

 - Asynchronous generators were introduced in 3.6
"""

from types import FunctionType,GeneratorType
from inspect import getsource,currentframe,findsource,getframeinfo
from copy import deepcopy,copy
from sys import version_info
from dis import get_instructions

## minium version supported ##
if version_info < (2,2):
    raise ImportError("""Python version 2.2 or above is required.

Note:

Python version 2.2 is when PEP 255 and 234 were implemented ('Simple Generators' and 'iterators') to the extent they
were implemented allowing for function generators with the 'yield' keyword and iterators. Version 2.4 introduced 
Generator expressions. Therefore, this python module/library is only useful for python versions 2.2 and above.
""")

#########################
### utility functions ###
#########################

if version_info < (2,3):
    from warnings import warn
    warn("Python version 2.3 or above is required for get_history_item for usage on CLIs",UserWarning)
    def is_cli():
        return False
else:
    from readline import get_history_item

    def is_cli():
        """Determines if using get_history_item is possible e.g. for CLIs"""
        try:
            get_history_item(0)
            return True
        except IndexError:
            return False

if version_info < (3,):
    range = xrange

if version_info < (3,4):
    def get_instructions(FUNC):
        pass

if version_info < (2,6):
    def next(iter_val,*args):
        """
        Return the next item from the iterator. If default is given and 
        the iterator is exhausted, it is returned instead of raising StopIteration.
        """
        if len(args) > 1:
            raise TypeError("next expected at most 2 arguments, got %s" % len(args))
        if args:
            try:
                return iter_val.next()
            except StopIteration:
                return args[0]
        return iter_val.next()

if version_info < (3,11):
    def get_col_offset(frame): ## shouldn't this be a different version??
        lasti=frame.f_lasti
        for instruction in get_instructions(frame.f_code):
            if instruction.offset==lasti:
                return instruction.positions.col_offset
        raise ValueError("f_lasti not encountered")
else:
    ## make an attr dict out of the tuple ##
    def get_col_offset(frame):
        return getframeinfo(frame).positions.col_offset
    

if version_info < (2,3):
    def enumerate(gen):
        """Enumerates a generator/iterator"""
        index=0
        for i in gen:
            yield index,i
            index+=1

def dedent(text):
    """
    simplified version of dedent from textwrap that 
    removes purely whitespace indentation from a string
    to the minimum indentation

    If you have python version 2.3 or higher you can use
    textwrap.dedent but I've decided to make an implementation
    specific version for python 2.2 and it should ideally be 
    faster for its specific use case
    """
    ## because I'm only using this for functions source code ##
    ## we can use the indent from the first line as the ##
    ## minimum indent and remove unnecessary whitespace ##
    indent=get_indent(text)
    if indent==0:
        return text
    text_iter,line,dedented=enumerate(text),-1,False
    text=""
    for index,char in text_iter:
        ## dedent the current line ##
        if not dedented:
            while char==" ":
                if not index-prev_split <= indent:
                    line=""
                    break
                line+=char
                index,char=next(text_iter)
            dedented=True
        ## collect the current line ##
        if char=="\n":
            prev_split,dedented=index,False
            if line.isspace(): ## remove unnecessary whitespace ##
                line=""
            text+=line+"\n"
            line=""
        ## gather the chars ##
        else:
            line+=char
    ## add the last line if it exists ##
    if line:
        text+=line
    return text

def get_indent(line):
    """Gets the number of spaces used in an indentation"""
    count=0
    for char in line:
        if char!=" ":
            break
        count+=1
    return count

def lineno_adjust(FUNC,frame=None):
    """
    unpacks a line of compound statements
    into lines up to the last instruction 
    that determines the adjustment required
    """
    if frame is None:
        frame=getframe(FUNC)
    line,current_lineno,instructions=[],frame.f_lineno,get_instructions(FUNC)
    ## get the instructions at the lineno ##
    for instruction in instructions:
        lineno,obj=instruction.positions.lineno,(list(instruction.positions[2:]),instruction.offset)
        if not None in obj[0] and lineno==current_lineno:
            ## get the lines ##
            line=[obj]
            for instruction in instructions:
                lineno,obj=instruction.positions.lineno,(list(instruction.positions[2:]),instruction.offset)
                if lineno!=current_lineno:
                    break
                line+=[obj]
            break
    ## add the lines
    if line:
        index,current,lasti=0,[0,0],frame.f_lasti
        for pos,offset in line.sort():
            if offset==lasti:
                return index
            if pos[0] > current[1]:
                current=pos
                index+=1
            elif pos[1] > current[1]:
                current[1]=pos[1]
    raise ValueError("f_lasti not encountered")

def unpack_genexpr(source):
    """unpacks a generator expressions' for loops into a list of source lines"""
    lines,line,ID,depth,prev,has_for,has_end_if=[],"","",0,(0,""),False,False
    source_iter=enumerate(source[1:-1])
    for index,char in source_iter:
        if char in "\\\n":
            continue
        ## collect strings
        if char=="'" or char=='"':
            if prev[0]-1==index and char==prev[1]:
                string_collector=collect_multiline_string
            else:
                string_collector=collect_string
            index,temp_line=string_collector(source_iter,char)
            prev=(index,char)
            line+=temp_line
            continue
        if char=="(":
            depth+=1
        elif char==")":
            depth-=1
        ## accumulate the current line
        line+=char
        ## collect IDs
        if char.isalnum():
            ID+=char
        else:
            ID=""
        if depth==0:
            if ID == "for" or ID == "if" and next(source_iter)[1] == " ":
                if ID =="for":
                    lines+=[line[:-3]]
                    line=line[-3:]#+" "
                    if not has_for:
                        has_for=len(lines) ## should be 1 anyway
                elif has_for:
                    lines+=[line[:-2],source[index:-1]] ## -1 to remove the end bracket - is this necessary?
                    has_end_if=True
                    break
                else:
                    lines+=[line[:-2]]
                    line=line[-2:]+" "
                # ID="" ## isn't necessary because you don't get i.e. 'for for' or 'if if' in python syntax
    if has_end_if:
        lines=lines[has_for:-1]+(lines[:has_for]+[lines[-1]])[::-1]
    else:
        lines=lines[has_for:]+(lines[:has_for])[::-1]
    ## arrange into lines
    indent=" "*4
    return [indent*index+line for index,line in enumerate(lines,start=1)]

################
### tracking ###
################

"""
Needs the col_offset in versions less than 
that of those without co_positions or 
FrameInfo.positions or get_instructions
"""
def isin_statement(source,frame):
    """Checks if a frame with its source is in a block statement"""
    ## Get the start and end offsets ##
    ## determine the offsets for the first statement ##
    for index,char in enumerate(source):
        ## skip strings ##
        ## ..
        if char == ":":
            if lineno_adjust(frame.f_code,frame):
                return False
            return True
    return False

def track_iter(obj):
    """
    Tracks an iterator in the local scope initiated by a for loop
    
    This function has a specific use case where the initialization
    of an iterator via a for loop implictely does not allow for 
    reliable extraction from the garbage collector and thus manually
    assigning the iterator for tracking is used

    Note: variables are signified as '.%s' % number_of_indents
    i.e.
        for i in range(3) is 4 indents and thus is assigned '.4'
    
    This way makes it more effective to retrieve the iterator
    rather than appending iterators. This means only numbers
    that are divisble by 4 should not be used in general usage
    by users.

    Using in generator expressions uses the col_offset instead
    """
    obj=iter(obj)
    frame=currentframe().f_back
    if frame.f_code.co_name=="<genexpr>":
        key=get_col_offset(frame)
    else:
        if is_cli():
            code_context=get_history_item(-frame.f_lineno)
        else:
            code_context=getframeinfo(frame).code_context[0]
        key=get_indent(code_context)
        ## won't work for compound statements that are in block statements ##
        ## therefore, we check for a block statement and add 4 if so ##
        temp=code_context[key:]
        if (temp.startswith("if ") or temp.startswith("for ") or \
            temp.startswith("while ") or is_definition(temp)) and not isin_statement(temp,frame):
            key+=4
    frame.f_locals[".%s" % key]=obj
    return obj

############################
### cleaning source code ###
############################

def skip_source_definition(source):
    """Skips the function definition and decorators in the source code"""
    ID,source_iter="",enumerate(source)
    for index,char in source_iter:
        ## decorators are ignored ##
        while char=="@":
            while char!="\n":
                index,char=next(source_iter)
            index,char=next(source_iter)
        if char.isalnum():
            ID+=char
            if len(ID)==3:
                if ID=="def" and next(source_iter)[1]==" ":
                    while char!="(":
                        index,char=next(source_iter)
                    break
                return source
        else:
            ID=""
    depth=1
    for index,char in source_iter:
        if char==":" and depth==0:
            return source[index+1:]
        if char in "([{":
            depth+=1
        elif char in ")]}":
            depth-=1
    raise SyntaxError("Unexpected format encountered")

def collect_string(iter_val,reference):
    """
    Collects strings in an iterable assuming correct 
    python syntax and the char before is a qoutation mark
    
    Note: make sure iter_val is an enumerated type
    """
    line,backslash=reference,False
    for index,char in iter_val:
        if char==reference and not backslash:
            line+=char
            break
        line+=char
        backslash=False
        if char=="\\":
            backslash=True
    return index,line

def collect_multiline_string(iter_val,reference):
    """
    Collects multiline strings in an iterable assuming 
    correct python syntax and the char before is a 
    qoutation mark
    
    Note: make sure iter_val is an enumerated type
    
    if a string starts with 3 qoutations
    then it's classed as a multistring
    """
    line,backslash,prev,count=reference,False,-2,0
    for index,char in iter_val:
        if char==reference and not backslash:
            if index-prev==1:
                count+=1
            else:
                count=0
            prev=index
            if count==2:
                line+=char
                break
        line+=char
        backslash=False
        if char=="\\":
            backslash=True
    return index,line

def collect_definition(line,lines,lineno,source,source_iter,reference_indent,prev):
    """
    Collects a block of code from source, specifically a 
    definition block in the case of this modules use case
    """
    indent=reference_indent+1
    while reference_indent < indent:
        ## we're not specific about formatting the definitions ##
        ## we just need to make sure to include them ##
        for index,char in source_iter:
            ## collect strings ##
            if char=="'" or char=='"':
                if prev[0]+2==prev[1]+1==index and prev[2]==char:
                    string_collector=collect_multiline_string
                else:
                    string_collector=collect_string
                temp_index,temp_line=string_collector(source_iter,char)
                prev=(index,temp_index,char)
                line+=temp_line
            ## newline ##
            elif char == "\n":
                break
            else:
                line+=char
        ## add the line and get the indentation to check if continuing ##
        lineno+=1
        lines+=[line]
        line,indent="",get_indent(source[index+1:])
    ## make sure to return the index and char for the indentation ##
    return index,char,lineno,lines

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

def is_definition(line):
    """Checks if a line is a definition"""
    return line.startswith("def ") or line.startswith("async def ") or\
           line.startswith("class ") or line.startswith("async class ")

########################
### code adjustments ###
########################
def skip_alternative_statements(line_iter,current_min):
    """Skips all alternative statements for the control flow adjustment"""
    for index,line in line_iter:
        temp_indent=get_indent(line)
        temp_line=line[temp_indent:]
        if temp_indent <= current_min and not is_alternative_statement(temp_line):
            break
    return index,line,temp_indent

def offset_adjust(f_locals):
    """
    Adjusts the track_iter created variables
    used in generator expressions from offset
    based to indentation based

    We have to do this because generator expressions
    can only have offset based trackers whereas
    when we format the source lines it requires
    indentation based

    Note: only needed on the current variables
    in the frame that use offset based trackers
    """
    ## the first offset will probably get in the way ##
    lineno=0 ## every line will increase the indentation by 4 ##
    for key,value in f_locals.items():
        if isinstance(key,str) and key[0]=="." and key[1:].isdigit():
            del f_locals[key]
            lineno+=1
            f_locals[4*lineno]=value
    return f_locals

def control_flow_adjust(lines,indexes,reference_indent=4):
    """
    removes unreachable control flow blocks that 
    will get in the way of the generators state

    Note: it assumes that the line is cleaned,
    in particular, that it starts with an 
    indentation of 4 (4 because we're in a function)

    It will also add 'try:' when there's an
    'except' line on the next minimum indent
    """
    new_lines,current_min=[],get_indent(lines[0])
    line_iter=enumerate(lines)
    for index,line in line_iter:
        temp_indent=get_indent(line)
        temp_line=line[temp_indent:]
        if temp_indent < current_min:
            ## skip over all alternative statements until it's not an alternative statement ##
            ## and the indent is back to the current min ##
            if is_alternative_statement(temp_line):
                end_index,line,temp_indent=skip_alternative_statements(line_iter,temp_indent)
                del indexes[index:end_index]
                index=end_index
            current_min=temp_indent
            if temp_line.startswith("except"):
                new_lines=[" "*4+"try:"]+indent_lines(new_lines)+[line[current_min-4:]]
                indexes=[indexes[0]]+indexes
        ## add the line (adjust if indentation is not reference_indent) ##
        if current_min != reference_indent:
            ## adjust using the current_min until it's the same as reference_indent ##
            new_lines+=[line[current_min-4:]]
        else:
            return new_lines+indent_lines(lines[index:],4-reference_indent),indexes
    return new_lines,indexes

def indent_lines(lines,indent=4):
    """indents a list of strings acting as lines"""
    if indent > 0:
        return [" "*indent+line for line in lines]
    if indent < 0:
        indent=-indent
        return [line[indent:] for line in lines]
    return lines

def extract_iter(line,number_of_indents):
    """
    Extracts the iterator from a for loop
    
    e.g. we extract the second ... in:
    for ... in ...:
    """
    depth,ID,line_iter=0,"",enumerate(line)
    for index,char in line_iter:
        if char=="(":
            depth+=1
        elif char==")":
            depth-=1
        if char.isalnum() and depth==0:
            ID+=char
            if ID=="in":
                if next(line_iter)[1]==" ":
                    break
                ID=""
        else:
            ID=""
    index+=2 ## adjust by 2 to skip the 'n' and ' ' in 'in ' that would've been deduced ##
    iterator=line[index:-1] ## -1 to remove the end colon ##
    ## remove the leading and trailing whitespace and then it should be a variable name ##
    if iterator.strip().isalnum():
        return line
    return line[:index]+"locals()['.%s']:" % number_of_indents

def iter_adjust(outer_loop):
    """adjust an outer loop with its tracked iterator if it uses one"""
    flag,line=False,outer_loop[0]
    number_of_indents=get_indent(line)
    if line[number_of_indents:].startswith("for "):
        outer_loop[0]=extract_iter(line,number_of_indents)
        flag=True
    return flag,outer_loop

def loop_adjust(lines,indexes,outer_loop,*pos):
    """
    Formats the current code block 
    being executed such that all the
    continue -> break;
    break -> empty the current iter; break;

    This allows us to use the control
    flow statements by implementing a
    simple for loop and if statement
    to finish the current loop
    """
    new_lines,flag,line_iter=[],False,enumerate(lines)
    for index,line in line_iter:
        indent=get_indent(line)
        temp_line=line[indent:]
        ## skip over for/while and definition blocks ##
        while temp_line.startswith("for ") or temp_line.startswith("while ") or is_definition(temp_line):
            for index,line in line_iter:
                temp_indent=get_indent(line)
                if temp_indent <= indent:
                    break
                new_lines+=[line]
            ## continue back ##
            indent=temp_indent
            temp_line=line[indent:]
        if temp_line.startswith("continue"):
            flag=True
            new_lines+=["break"]
        elif temp_line.startswith("break"):
            flag=True
            new_lines+=["locals()['.continue']=False","break"]
            indexes=indexes[index:]+indexes[index]+indexes[:index]
        else:
            new_lines+=[line]
    ## adjust it in case it's an iterator ##
    flag,outer_loop=iter_adjust(outer_loop)
    if flag:
        return ["    locals()['.continue']=True","    for _ in ():"]+indent_lines(new_lines,8-get_indent(new_lines[0]))+\
               ["    if locals()['.continue']:"]+indent_lines(outer_loop,8-get_indent(outer_loop[0])),\
               [indexes[0],indexes[0]]+indexes+[pos[0]]+list(range(*pos))
    return indent_lines(lines,4-get_indent(lines[0]))+indent_lines(outer_loop,4-get_indent(outer_loop[0])),indexes+list(range(*pos))

def has_node(line,node):
    """Checks if a node has starting IDs that match"""
    ID,nodes,checks="",[],node.split()
    for char in line:
        ## no strings allowed ##
        if char=="'" or char=='"':
            return False
        if char.isalnum():
            ID+=char
        elif char==" ":
            if ID:
                nodes+=[ID]
                for node,check in zip(nodes,checks):
                    if node!=check:
                        return False
                if len(nodes)==len(checks):
                    return True
    return False

def send_adjust(line):
    """Checks for variables assigned to yields for making adjustments"""
    parts,flag=line.split("="),0
    for index,node in enumerate(parts):
        node=node[get_indent(node):]
        if has_node(node,"yield from "):
            flag=1
            break
        if has_node(node,"yield "):
            flag=2
            break
    if flag:
        reciever="="
        if flag == 2:
            reciever+="locals()['.send']"
        ## indicator       yield statement            assignments
        return flag,["=".join(parts[index:]),"=".join(parts[:index])+reciever]
    return None,None

def get_loops(lineno,jump_positions):
    """
    returns a list of tuples (start_lineno,end_lineno) for the loop 
    positions in the source code that encapsulate the current lineno
    """
    ## get the outer loops that contian the current lineno ##
    loops=[]
    ## jump_positions are in the form (start_lineno,end_lineno) ##
    for pos in jump_positions: ## importantly we go from start to finish to capture nesting loops ##
        ## make sure the lineno is contained within the position for a ##
        ## loop adjustment and because the jump positions are ordered we ##
        ## can also break when the start lineno is beyond the current lineno ##
        if lineno < pos[0]:
            break
        if lineno < pos[1]:
            loops+=[pos]
    return loops

######################
### expr_getsource ###
######################
def code_attrs():
    """
    all the attrs used by a CodeType object in 
    order of types.CodeType function signature 
    ideally and correct to the current version
    """
    attrs=("co_argcount",)
    if (3,8) <= version_info:
        attrs+=("co_posonlyargcount",)
    attrs+=("co_kwonlyargcount","co_nlocals","co_stacksize","co_flags","co_code",
            "co_consts", "co_names", "co_varnames", "co_filename", "co_name")
    if (3,3) <= version_info:
        attrs+=("co_qualname",)
    attrs+=("co_firstlineno",)
    if (3,10) <= version_info:
        attrs+=("co_linetable",)
    else:
        attrs+=("co_lnotab",)
    if (3,11) <= version_info:
        attrs+=("co_exceptiontable",)
    attrs+=("co_freevars","co_cellvars")
    return attrs

def attr_cmp(obj1,obj2,attrs):
    """Compares two objects by a collection of their attrs"""
    for attr in attrs:
        if getattr(obj1,attr)!=getattr(obj2,attr):
            return False
    return True

def getcode(obj):
    """Gets the code object from an object via commonly used attrs"""
    for attr in ["__code__","gi_code","ag_code","cr_code"]:
        if hasattr(obj,attr):
            return getattr(obj,attr)
    raise AttributeError("code object not found")

def getframe(obj):
    """Gets the frame object from an object via commonly used attrs"""
    for attr in ["gi_frame","ag_frame","cr_frame"]:
        if hasattr(obj,attr):
            return getattr(obj,attr)
    raise AttributeError("frame object not found")

def expr_getsource(FUNC):
    """
    Uses co_positions or otherwise goes through the source code 
    extracting expressions until a match is found on a code object 
    basis to get the source

    Note:
    the extractor should return a string and if using a 
    lambda extractor it will take in a string input but
    if using a generator expression extractor it will 
    take a list instead
    """
    code_obj=getcode(FUNC)
    if code_obj.co_name=="<lambda>":
        ## here source is a : str
        source=getsource(code_obj)
        extractor=extract_lambda
    else:
        lineno=getframe(FUNC).f_lineno-1
        ## here source is a : list[str]
        source=findsource(code_obj)[0][lineno:]
        extractor=extract_genexpr
    ## get the rest of the source ##
    if (3,11) <= version_info:
        # start_line, end_line, start_col, end_col
        positions=code_obj.co_positions()
        is_source_list=isinstance(source,list)
        pos=next(positions,(None,None,None))[1:]
        current_min,current_max=pos[2:]
        if is_source_list:
            current_max_lineno=pos[1]
        for pos in positions:
            if pos[-2] and pos[-2] < current_min:
                current_min=pos[-2]
            if pos[-1] and pos[-1] > current_max:
                current_min=pos[-1]
            if is_source_list and pos[1] and pos[1] > current_max_lineno:
                current_max_lineno=pos[1]
        if is_source_list:
            source="\n".join(source[:current_max_lineno+1])
        return source[current_min:current_max]
    ## otherwise match with generator expressions in the original source to get the source code ##
    attrs=(attr for attr in code_attrs() if not attr in ('co_argcount','co_posonlyargcount','co_kwonlyargcount',
                                                         'co_filename','co_linetable','co_lnotab','co_exceptiontable'))
    for source in extractor(source):
        try: ## we need to make it a try-except in case of potential syntax errors towards the end of the line/s ##
            ## eval should be safe here assuming we have correctly extracted the expression - we can't use compile because it gives a different result ##
            if attr_cmp(getcode(eval(source)),code_obj,attrs):
                return source
        except:
            pass
    raise Exception("No matches to the original source code found")
###############
### genexpr ###
###############
def extract_genexpr(source_lines):
    """Extracts each generator expression from a list of the source code lines"""
    source,ID,is_genexpr,number_of_expressions,depth,prev="","",False,0,0,(0,"")
    for line in source_lines:
        ## if it's a new_line and you're looking for the next genexpr then it's not found ##
        if number_of_expressions:
            raise Exception("No matches to the original source code found")
        line=enumerate(line)
        for index,char in line:
            ## skip all strings if not in depth
            if char=="'" or char=='"':
                if prev[0]-1==index and char==prev[1]:
                    string_collector=collect_multiline_string
                else:
                    string_collector=collect_string
                index,temp_line=string_collector(line,char)
                prev=(index,char)
                if depth:
                    source+=temp_line
                continue
            ## detect brackets
            elif char=="(":
                depth+=1
            elif char==")":
                depth-=1
                if depth==0:
                    if is_genexpr:
                        yield source+char
                        number_of_expressions+=1
                        is_genexpr=False
                    source,ID="",""
                continue
            ## record source code ##
            if depth:
                source+=char
                ## record ID ##
                if char.isalnum():
                    ID+=char
                    ## detect a for loop
                    if ID=="for":
                        is_genexpr=True
                else:
                    ID=""

##############
### lambda ###
##############
def extract_lambda(source_code):
    """Extracts each lambda expression from the source code string"""
    source,ID,is_lambda,lambda_depth,prev="","",False,0,(0,"")
    source_code=enumerate(source_code)
    for index,char in source_code:
        ## skip all strings if not in lambda
        if char=="'" or char=='"':
            if prev[0]-1==index and char==prev[1]:
                string_collector=collect_multiline_string
            else:
                string_collector=collect_string
            index,temp_line=string_collector(source_code,char)
            prev=(index,char)
            if is_lambda:
                source+=temp_line
            continue
        ## detect brackets
        elif char=="(":
            depth+=1
        elif char==")":
            depth-=1
        ## record source code ##
        if is_lambda:
            if char=="\n;" or (char==")" and depth+1==lambda_depth): # lambda_depth needed in case of brackets; depth+1 since depth would've got reduced by 1
                yield source
                source,ID,is_lambda="","",False
            else:
                source+=char
        else:
            ## record ID ##
            if char.isalnum():
                ID+=char
                ## detect a lambda
                if ID == "lambda" and depth <= 1:
                    is_lambda=True
                    lambda_depth=depth
                    source+=ID
            else:
                ID=""
    ## in case of a current match ending ##
    if is_lambda:
        yield source
########################
### pickling/copying ###
########################
class Pickler(object):
    """
    class for allowing general copying and pickling of 
    some otherwise uncopyable or unpicklable objects
    """
    _not_allowed=tuple()

    def _copier(self,FUNC):
        """copying will create a new generator object but the copier will determine it's depth"""
        items=((attr,FUNC(getattr(self,attr))) for attr in self._attrs if hasattr(self,attr))
        obj=type(self)()
        obj.__setstate__(dict(items))
        return obj

    ## for copying ##
    def __copy__(self):
        return self._copier(copy)

    def __deepcopy__(self,memo):
        return self._copier(deepcopy)
    ## for pickling ##
    def __getstate__(self):
        """Serializing pickle (what object you want serialized)"""
        return dict(
                    (attr,getattr(self,attr)) for attr in self._attrs 
                    if hasattr(self,attr) and not attr in self._not_allowed
                )

    def __setstate__(self,state):
        """Deserializing pickle (returns an instance of the object with state)"""
        for key,value in state.items():
            setattr(self,key,value)

class frame(Pickler):
    """
    acts as the initial FrameType
    
    Note: on pickling ensure f_locals 
    and f_back can be pickled
    """
    _attrs=('f_back','f_code','f_lasti','f_lineno','f_locals',
            'f_trace','f_trace_lines','f_trace_opcodes')
    _not_allowed=("f_globals",)
    f_locals={}
    f_lineno=1
    f_globals=globals()
    f_builtins=__builtins__

    def __init__(self,frame=None):
        if frame:
            if hasattr(frame,"f_back"): ## make sure all other frames are the custom type as well ##
                self.f_back=type(self)(frame.f_back)
            if hasattr(frame,"f_code"): ## make sure it can be pickled
                self.f_code=code(frame.f_code)
            for attr in self._attrs[2:]:
                setattr(self,attr,getattr(frame,attr))
    
    def clear(self):
        """clears f_locals e.g. 'most references held by the frame'"""
        self.f_locals={}
    
    ## we have to implement this if I'm going to go 'if frame:' (i.e. in frame.__init__) ##
    def __bool__(self):
        """Used on i.e. if frame:"""
        for attr in ('f_code','f_lasti','f_lineno','f_locals'):
            if not hasattr(self,attr):
                return False
        return True
    
    if version_info < (3,5):
        __nonzero__=__bool__

class code(Pickler):
    """For pickling and copying code objects"""

    _attrs=code_attrs()

    def __init__(self,code_obj=None):
        if code_obj:
            for attr in self._attrs:
                setattr(self,attr,getattr(code_obj,attr))

    def __bool__(self):
        """Used on i.e. if code_obj:"""
        for attr in self._attrs:
            if not hasattr(self,attr):
                return False
        return True

    if version_info < (3,0):
        __nonzero__=__bool__

#################
### Generator ###
#################
"""
TODO:

1. general testing and fixing to make sure everything works before any more changes are made

    Needs checking:

    - extract_lambda and extract_genexpr need to handle excessive bracketing i.e. 
      (( i for i in range(3) )) but not (( i for i in range(3) )+1)

    - check .send on generator expressions and in general for those that don't use it

    - check lineno_adjust to ensure that it's robust, not sure if it works in all cases

    format errors
    - maybe edit or add to the exception traceback in __next__ so that the file and line number are correct
    - with throw, extract the first line from self.state (for cpython) and then create an exception traceback out of that
    (if wanting to port onto jupyter notebook you'd use the entire self._source_lines and then point to the lineno)

    -----------------------------------------------
    Backwards compatibility:
    -----------------------------------------------
    - finish get_instructions - make sure the positions and offsets are correct
    -----------------------------------------------

2. make an asynchronous verion? async generators have different attrs i.e. gi_frame is ag_frame
 - maybe make a preprocessor to rewrite some of the functions in Generator for ease of development
 - use getcode and getframe for more generalizability
   also consider coroutines e.g. cr_code, cr_frame, etc.
    
3. write tests

control_flow_adjust - test to see if except does get included as a first line of a state (it shouldn't)
need to test what happens when there are no lines e.g. empty lines or no state / EOF

"""
class Generator(Pickler):
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
        temp_line=line[number_of_indents:]
        indent=" "*number_of_indents
        if temp_line.startswith("yield from "):
            return [indent+"currentframe().f_back.f_locals['.yieldfrom']="+temp_line[11:],
                    indent+"for currentframe().f_back.f_locals['.i'] in currentframe().f_back.f_locals['.yieldfrom']:",
                    indent+"    return currentframe().f_back.f_locals['.i']"]
        if temp_line.startswith("yield "):
            return [indent+"return"+temp_line[5:]] ## 5 to retain the whitespace ##
        if temp_line.startswith("for ") or temp_line.startswith("while "):
            self.jump_positions+=[[lineno,None]] ## has to be a list since we're assigning ##
            self._jump_stack+=[(number_of_indents,len(self.jump_positions)-1)] ## doesn't have to be a list since it'll get popped e.g. it's not really meant to be modified as is ##
            return [line]
        if temp_line.startswith("return "):
            ## close the generator then return ##
            return [indent+"currentframe().f_back.f_locals['self'].close()",line]
        ## handles the .send method ##
        flag,adjustment=send_adjust(temp_line)
        if flag:
            if flag==2:
                ## 5: to get past the 'yield'
                return [indent+"return"+adjustment[0][5:],
                        indent+adjustment[1]]
            else:
                ## 11: to get past the 'yield from'
                return [indent+"currentframe().f_back.f_locals['.yieldfrom']="+adjustment[0][11:],
                        indent+"for currentframe().f_back.f_locals['.i'] in currentframe().f_back.f_locals['.yieldfrom']:",
                        indent+"    return currentframe().f_back.f_locals['.i']",
                        indent+"    %scurrentframe().f_back.f_locals['.yieldfrom'].send(currentframe().f_back.f_locals['.send'])" % adjustment[1]]
        return [line]

    def _clean_source_lines(self,running=False):
        """
        source: str

        returns source_lines: list[str],return_linenos: list[int]

        1. fixes any indentation issues (when ';' is used) and skips empty lines
        2. split on "\n", ";", and ":"
        3. join up the line continuations i.e. "\ ... " will be skipped
        
        additionally, custom_adjustment will be called on each line formation as well

        Note:
        jump_positions: are the fixed list of (lineno,end_lineno) for the loops (for and while)
        _jump_stack: jump_positions currently being recorded (gets popped into jump_positions once 
                     the reference indent has been met or lower for the next line that does so)
                     it records a tuple of (reference_indent,jump_position_index)
        """
        ## for loop adjustments ##
        self.jump_positions,self._jump_stack,lineno=[],[],0
        ## setup source as an iterator and making sure the first indentation's correct ##
        source=skip_source_definition(self.source)
        source=source[get_indent(source):] ## we need to make sure the source is saved for skipping for line continuations ##
        source_iter=enumerate(source)
        line,lines,indented,space,indentation,prev=" "*4,[],False,0,4,(0,0,"")
        ## enumerate since I want the loop to use an iterator but the 
        ## index is needed to retain it for when it's used on get_indent
        for index,char in source_iter:
            ## collect strings ##
            if char=="'" or char=='"':
                if prev[0]+2==prev[1]+1==index and prev[2]==char:
                    string_collector=collect_multiline_string
                else:
                    string_collector=collect_string
                temp_index,temp_line=string_collector(source_iter,char)
                prev=(index,temp_index,char)
                line+=temp_line
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
                skip(source_iter,get_indent(source[index+1:])) ## +1 since 'index:' is inclusive ##
            ## create new line ##
            elif char in "#\n;:":
                ## skip comments ##
                if char=="#":
                    for index,char in source_iter:
                        if char == "\n":
                            break
                ## make sure to include it ##
                if char==":":
                    indentation=get_indent(line)+4 # in case of ';'
                    line+=char
                if not line.isspace(): ## empty lines are possible ##
                    reference_indent=get_indent(line)
                    if self._jump_stack:
                        end_lineno=len(lines)+1
                        while self._jump_stack and reference_indent <= self._jump_stack[-1][0]: # -1: top of stack, 0: start lineno
                            self.jump_positions[self._jump_stack.pop()[1]][1]=end_lineno ## +1 assuming exclusion slicing on the stop index ##
                    ## skip the definitions ##
                    if is_definition(line[reference_indent:]):
                        index,char,lineno,lines=collect_definition(line,lines,lineno,source,source_iter,reference_indent,prev)
                    else:
                        lineno+=1
                        lines+=self._custom_adjustment(line,lineno)
                        ## make a linetable if using a running generator ##
                        if running and char=="\n":
                            self.linetable+=[lineno]
                ## start a new line ##
                if char in ":;":
                    # just in case
                    indented,line=True," "*indentation
                else:
                    indented,line=False,""
                space=index ## this is important (otherwise we get more indents than necessary) ##
            else:
                line+=char
        ## in case you get a for loop at the end and you haven't got the end jump_position ##
        ## then you just pop them all off as being the same end_lineno ##
        end_lineno=len(lines)+1
        while self._jump_stack:
            self.jump_positions[self._jump_stack.pop()[1]][1]=end_lineno
        ## are not used by this generator (was only for formatting source code and 
        ## recording the jump positions needed in the for loop adjustments) ##
        del self._jump_stack
        return lines

    def _create_state(self,loops):
        """
        creates a section of modified source code to be used in a 
        function to act as a generators state

        The approach is as follows:

        Use the entire source code, reducing from the last lineno.
        Adjust the current source code reduction further out of
        control flow statements, loops, etc. then set the adjusted 
        source code as the generators state

        Adjusts source code about control flow statements
        so that it can be used in a single directional flow
        as the generators states

        to handle nesting of loops it will simply join
        all the loops together and run them where the 
        outermost nesting will be the final section that
        also contains the rest of the source lines as well
        """
        temp_lineno=self.lineno-1 ## for 0 based indexing ##
        if loops:
            start_pos,end_pos=loops.pop()
            ## for 0 based indexing since they're linenos ##
            start_pos-=1
            end_pos-=1
            ## adjustment ##
            blocks,indexes=control_flow_adjust(
                self._source_lines[temp_lineno:end_pos],
                list(range(temp_lineno,end_pos)),
                get_indent(self._source_lines[start_pos])
            )
            blocks,indexes=loop_adjust(
                blocks,indexes,
                self._source_lines[start_pos:end_pos],
                *(start_pos,end_pos)
            )
            self.linetable=indexes
            ## add all the outer loops ##
            for start_pos,end_pos in loops[::-1]:
                start_pos-=1
                end_pos-=1
                flag,block=iter_adjust(self._source_lines[start_pos:end_pos])
                blocks+=indent_lines(block,4-get_indent(block[0]))
                if flag:
                    self.linetable+=[start_pos]
                self.linetable+=list(range(start_pos,end_pos))
            self.state="\n".join(blocks+self._source_lines[end_pos:])
            return
        block,self.linetable=control_flow_adjust(
            self._source_lines[temp_lineno:],
            list(range(temp_lineno,len(self._source_lines)))
        )
        self.state="\n".join(block)

    def _locals(self):
        """
        proxy to replace locals within 'next_state' within 
        __next__ while still retaining the same functionality
        """
        return self.gi_frame.f_locals
    
    def _init(self):
        """
        initializes the frame with the current 
        states variables and the _locals proxy
        """
        assign=[" "*4+key+"=locals()['"+key+"']" for key in self.gi_frame.f_locals \
                if isinstance(key,str) and key.isalnum() and key!="locals"]
        if assign:
            assign="\n"+"\n".join(assign)
        else:
            assign=""
        ## try not to use variables here (otherwise it can mess with the state) ##
        return """def next_state():
    locals=currentframe().f_back.f_locals['self']._locals%s
    currentframe().f_back.f_locals['.frame']=currentframe()
""" % assign

    def init_states(self):
        """Initializes the state generation as a generator"""
        ## since self.state starts as 'None' ##
        yield self._create_state(get_loops(self.lineno,self.jump_positions))
        loops=get_loops(self.lineno,self.jump_positions)
        while (self.state and len(self.linetable) > self.gi_frame.f_lineno) or loops:
            yield self._create_state(loops)
            loops=get_loops(self.lineno,self.jump_positions)

    _attrs=('_source_lines','gi_code','gi_frame','gi_running',
            'gi_suspended','gi_yieldfrom','jump_positions','lineno','source')

    def __init__(self,FUNC=None,overwrite=False):
        """
        Takes in a function/generator or its source code as the first arguement

        If FUNC=None it will simply initialize as without any attributes, this
        is for the __setstate__ method in Pickler._copier use case

        Note:
         - gi_running: is the generator currently being executed
         - gi_suspended: is the generator currently paused e.g. state is saved
        """
        ## __setstate__ from Pickler._copier ##
        if not FUNC is None:
            ## running generator ##
            if hasattr(FUNC,"gi_code"):
                self.linetable=[]
                self.gi_frame=frame(FUNC.gi_frame)
                if FUNC.gi_code.co_name=="<genexpr>": ## co_name is readonly e.g. can't be changed by user ##
                    self.source=expr_getsource(FUNC)
                    self._source_lines=unpack_genexpr(self.source)
                    ## change the offsets into indents ##
                    self.gi_frame.f_locals=offset_adjust(self.gi_frame.f_locals)
                else:
                    self.source=dedent(getsource(FUNC.gi_code))
                    self._source_lines=self._clean_source_lines(True)
                    self.lineno=self.linetable[FUNC.gi_frame.f_lineno-1]+lineno_adjust(FUNC)
                self.gi_code=code(FUNC.gi_code)
                ## 'gi_yieldfrom' was introduced in python version 3.5 and yield from ... in 3.3 ##
                if hasattr(FUNC,"gi_yieldfrom"):
                    self.gi_yieldfrom=FUNC.gi_yieldfrom
                else:
                    self.gi_yieldfrom=None
                self.gi_suspended=True
            ## uninitialized generator ##
            else:
                ## source code string ##
                if isinstance(FUNC,str):
                    self.source=FUNC
                    self.gi_code=code(compile(FUNC,"","eval"))
                ## generator function ##
                elif isinstance(FUNC,FunctionType):
                    if FUNC.__code__.co_name=="<lambda>":
                        self.source=expr_getsource(FUNC)
                    else:
                        self.source=dedent(getsource(FUNC))
                    self.gi_code=code(FUNC.__code__)
                else:
                    raise TypeError("type '%s' is an invalid initializer for a Generator" % type(FUNC))
                ## make sure the source code is standardized and usable by this generator ##
                self._source_lines=self._clean_source_lines()
                ## create the states ##
                self.gi_frame=frame()
                self.gi_suspended=False
                self.gi_yieldfrom=None
                self.lineno=1 ## modified every time __next__ is called; always start at line 1 ##
            self.gi_running=False
            self.state=None
            self.state_generator=self.init_states()
            if overwrite:
                currentframe().f_back.f_locals[getcode(FUNC).co_name]=self

    def __len__(self):
        """
        Gets the number of states for generators with 
        yield statements indented exactly 4 spaces.

        In general, you shouldn't be able to get the length
        of a generator function, but if it's very predictably
        defined then you can.
        """
        def number_of_yields():
            """Gets the number of yields that are indented exactly 4 spaces"""
            for line in self.state:
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
        """updates the current state and returns the result"""
        # set the next state and setup the function
        next(self.state_generator) ## it will raise a StopIteration for us
        ## update with the new state and get the frame ##
        exec(self._init()+self.state,globals(),locals())
        self.gi_running=True
        ## if an error does occur it will be formatted correctly in cpython (just incorrect frame and line number) ##
        try:
            return locals()["next_state"]()
        finally:
            ## update the line position and frame ##
            self.gi_running=False
            ## update the frame ##
            f_back=self.gi_frame
            self.gi_frame=locals()[".frame"]
            if self.gi_frame:
                self.gi_frame=frame(self.gi_frame)
                ## remove locals from memory since it interferes with pickling ##
                del self.gi_frame.f_locals["locals"]
                self.gi_frame.f_back=f_back
                ## update f_locals ##
                if f_back:
                    f_back.f_locals.update(self.gi_frame.f_locals)
                    self.gi_frame.f_locals=f_back.f_locals
                self.gi_frame.f_locals[".send"]=None
                self.gi_frame.f_lineno=self.gi_frame.f_lineno-self.init.count("\n")
                if len(self.linetable) > self.gi_frame.f_lineno:
                    self.lineno=self.linetable[self.gi_frame.f_lineno]+1 ## +1 to get the next lineno after returning ##
                else:
                    ## EOF ##
                    self.lineno=len(self._source_lines)+1

    def send(self,arg):
        """
        Send takes exactly one arguement 'arg' that 
        is sent to the functions yield variable
        """
        if not self.gi_running:
            raise TypeError("can't send non-None value to a just-started generator")
        # if self.gi_yieldfrom:
        #     self.gi_yieldfrom.send(arg)
        #     return
        self.gi_frame.f_locals()[".send"]=arg
        return next(self)

    def close(self):
        """Creates a simple empty generator"""
        self.state_generator=iter(())
        self.gi_frame=None
        self.gi_running=False
        self.gi_suspended=False
        self.gi_yieldfrom=None

    def throw(self,exception):
        """
        Raises an exception from the last line in the 
        current state e.g. only from what has been
        """
        raise exception

    def __setstate__(self,state):
        Pickler.__setstate__(self,state)
        self.state_generator=self.init_states()

    def __instancecheck__(self, instance):
        return isinstance(instance,AnyGeneratorType)

    def __subclasscheck__(self, subclass):
        return issubclass(subclass,AnyGeneratorType)

AnyGeneratorType=GeneratorType|Generator

## add the type annotations if the version is 3.5 or higher ##
if (3,6) <= version_info:
    from types import AsyncGeneratorType
    AnyGeneratorType|=AsyncGeneratorType

if (3,5) <= version_info:
    from typing import Callable,Any,NoReturn,Iterable
    from types import CodeType,FrameType,CoroutineType
    
    AnyGeneratorType|=CoroutineType
    ## utility functions ##
    lineno_adjust.__annotations__={"FUNC":AnyGeneratorType,"return":int}
    is_cli.__annotations__={"return":bool}
    unpack_genexpr.__annotations__={"source":str,"return":list[str]}
    ## tracking ##
    isin_statement.__annotations__={"source":str,"frame":FrameType,"return":bool}
    track_iter.__annotations__={"obj":object,"return":Iterable}
    ## cleaning source code ##
    skip_source_definition.__annotations__={"source":str,"return":str}
    collect_string.__annotations__={"iter_val":enumerate,"reference":str,"return":str}
    collect_multiline_string.__annotations__={"iter_val":enumerate,"reference":str,"return":str}
    collect_definition.__annotations__ = {"line": str,"lines": list[str],"lineno": int,"source": str,"source_iter": enumerate,"reference_indent": int,"prev": tuple[int, str],"return": tuple[int, str, int,list[str]]}
    get_indent.__annotations__={"line":str,"return":int}
    skip.__annotations__={"iter_val":Iterable,"n":int,"return":None}
    is_alternative_statement.__annotations__={"line":str,"return":bool}
    ## code adjustments ##
    skip_alternative_statements.__annotations__={"line_iter":enumerate,"return":tuple[int,str,int]}
    offset_adjust.__annotations__={"f_locals":dict,"return":dict}
    control_flow_adjust.__annotations__={"lines":list[str],"indexes":list[int],"return":tuple[bool,list[str],list[int]]}
    indent_lines.__annotations__={"lines":list[str],"indent":int,"return":list[str]}
    extract_iter.__annotations__={"line":str,"number_of_indents":int|None,"return":str}
    iter_adjust.__annotations__={"outer_loop":list[str],"return":tuple[bool,list[str]]}
    loop_adjust.__annotations__={"lines":list[str],"indexes":list[int],"outer_loop":list[str],"pos":tuple[int,int],"return":tuple[list[str],list[int]]}
    has_node.__annotations__={"line":str,"node":str,"return":bool}
    send_adjust.__annotations__={"line":str,"return":tuple[None|int,None|list[str,str]]}
    get_loops.__annotations__={"lineno":int,"jump_positions":list[tuple[int,int]],"return":list[tuple[int,int]]}
    ## expr_getsource ##
    code_attrs.__annotations__={"return":tuple[str,...]}
    attr_cmp.__annotations__={"obj1":object,"obj2":object,"attr":tuple[str,...],"return":bool}
    getcode.__annotations__={"obj":AnyGeneratorType,"return":CodeType}
    getframe.__annotations__={"obj":AnyGeneratorType,"return":FrameType}
    expr_getsource.__annotations__={"FUNC":AnyGeneratorType,"return":str}
    ## genexpr ##
    extract_genexpr.__annotations__={"source_lines":list[str],"return":GeneratorType}
    ## lambda ##
    extract_lambda.__annotations__={"source_code":str,"return":GeneratorType}
    ### copying/pickling ###
    Pickler.__copy__.__annotations__={"return":Pickler}
    Pickler.__deepcopy__.__annotations__={"memo":dict,"return":Pickler}
    Pickler.__getstate__.__annotations__={"return":dict}
    Pickler.__setstate__.__annotations__={"state":dict,"return":None}
    frame.__init__.__annotations__={"frame":FrameType|None,"return":None}
    frame.clear.__annotations__={"return":None}
    frame.__bool__.__annotations__={"return":bool}
    code.__init__.__annotations__={"code":CodeType|None,"return":None}
    code.__bool__.__annotations__={"return":bool}
    ### Generator ###
    Generator._custom_adjustment.__annotations__={"line":str,"lineno":int,"return":list[str]}
    Generator._clean_source_lines.__annotations__={"return":list[str]}
    Generator._create_state.__annotations__={"return":None}
    Generator.init_states.__annotations__={"return":Iterable}
    Generator.__init__.__annotations__={"FUNC":AnyGeneratorType|str|None,"return":None}
    Generator.__len__.__annotations__={"return":int}
    Generator.__iter__.__annotations__={"return":Iterable}
    Generator.__next__.__annotations__={"return":Any}
    Generator.send.__annotations__={"arg":Any,"return":Any}
    Generator.close.__annotations__={"return":None}
    Generator.throw.__annotations__={"exception":Exception,"return":NoReturn}
    Generator._copier.__annotations__={"FUNC":Callable,"return":Generator}
    Generator.__copy__.__annotations__={"return":Generator}
    Generator.__deepcopy__.__annotations__={"memo":dict,"return":Generator}
    Generator.__getstate__.__annotations__={"return":dict}
    Generator.__setstate__.__annotations__={"state":dict,"return":None}
