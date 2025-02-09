
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

 - ternary conditionals were introduced in python 2.5


 Backwards compatibility notes of relevance at the moment:

reference for versions not available on the 
cpython github repo or as an alternative for 
where documentation is lacking: https://hg.python.org/cpython/file/2.2


## minium version supported ##
if version_info < (2,2):
    raise ImportError("""Python version 2.2 or above is required.

Note:

Python version 2.2 is when PEP 255 and 234 were implemented ('Simple Generators' and 'iterators') to the extent they
were implemented allowing for function generators with the 'yield' keyword and iterators. Version 2.4 introduced 
Generator expressions. Therefore, this python module/library is only useful for python versions 2.2 and above.



"""
TODO:

1. general testing and fixing to make sure everything works before any more changes are made

    Needs fixing:

    - detect f-strings in collect_string and collect_multiline_string

    - detect value yields in _clean_source_lines

     - yield_adjust - need to fix for yields used as values
      - unpacker - (yield 3),3,(yield 5),None
      - unwrapper - yield (yield (yield 5))
        
        and f'{yield 4}' or '%s' % (yield 5) are also possible
        also (yield None)

        adjust these before hand an then replace with actual 
        values during _clean_source_lines
    
    - add the yield adjust to the existing lines before the current line

    Needs checking:

    - check lineno_adjust to ensure that it's robust, not sure if it works in all cases.
      It relies on a single line containing all the code, it might be possible that you
      can have multiple independent expressions in one line but I haven't checked. -
      This function is only to help with users that choose to use compound statements.
    
    - check .send on generator expressions and in general for those that don't use it

    format errors
    - maybe edit or add to the exception traceback in __next__ so that the file and line number are correct
    - with throw, extract the first line from self._internals["state"] (for cpython) and then create an exception traceback out of that
    (if wanting to port onto jupyter notebook you'd use the entire self._internals["source_lines"] and then point to the lineno)

    -----------------------------------------------
    Backwards compatibility:
    -----------------------------------------------
    - finish get_instructions - make sure the positions and offsets are correct
      - used to get the current col_offset for track_iter on genexprs + for lineno_adjust
    -----------------------------------------------
 
2. write tests

control_flow_adjust - test to see if except does get included as a first line of a state (it shouldn't)
need to test what happens when there are no lines e.g. empty lines or no state / EOF

"""