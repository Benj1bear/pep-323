"""
TODO:

  - finish testing + review everything and check for any more relevant unforseen cases


  Needs implementation:
  - finally block from for multiple try-except catches
  - rewrite except_adjust in terms of except_catch_adjust
    and make sure to raise the error at the end if it's not caught
  - fix collect_definition
  - all unpacked lines need to be indented to the current indent

  Needs testing:
  - test is_item + extract_as + except_catch_adjust
  - clean_source_lines and its dependencies
    - test closing up of brackets
    - check the lineno from unpacking for initialized generators
  - block_adjust:
    - jump_positions
    - while loop adjust
    - other adjustments


  Currently not working (_clean_source_lines):
  - some value yields in f-strings in statements
  - a colon is added in a new line instead of the current
    line for while loops adjusted by _block_adjust or unpack


  Figure out later:
  - figure out examples of how to use ag_await and then cater for it if relevant

    utils:
      - test utils.cli_getsource
  - consider making patch iterators scope specific
    - finish testing patch_iterators with testing this
  - consider determining lineno given encapsulated yield and the send values
   - test_lambda_expr in test_custom_generator for encapsulated yields
"""
