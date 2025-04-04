"""
TODO:

  finish testing + review everything

  clean_source_lines:
    to be checked:
    - indentation of lines from unpacking in clean_source_lines needs checking
    - test closing up of brackets for both unpack + clean_source_lines
    - collect lambda needs checking
    - decorators needs checking
    - value yields e.g. decorators/functions/ternary
    - loops
    - check the lineno from unpacking for initialized generators
      - check that all unpacked lines are indented where necessary
        and indentation of future lines must also be considered
    - lineno for initialized generators needs checking

  check block_adjust

  unpack:
  - check the line continuation is adjusting correctly
    or consider removing char in " \\" case since it's
    only for formatting


  Figure out later:
    source_processing:
      - fix extract_function for expr_getsource tests
        - then test it in test_source_processing:
          - test_expr_getsource
          - test_extract_function

  - examples of how to use ag_await and then cater for it if relevant

  utils:
    - test utils.cli_getsource
  - consider making patch iterators scope specific
    - finish testing patch_iterators with testing this
  - consider determining lineno given encapsulated yield and the send values
   - test_lambda_expr in test_custom_generator for encapsulated yields
"""
