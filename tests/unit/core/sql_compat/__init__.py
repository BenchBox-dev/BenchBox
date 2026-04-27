# sql_compat unit tests
#
# Parametrize naming convention: use 'bmark' (not 'benchmark') for any
# @pytest.mark.parametrize argument that holds a benchmark name string.
# The pytest-benchmark plugin injects a 'benchmark' fixture; shadowing it
# with a parametrize argument of the same name causes INTERNALERROR at
# collection time.  All compat test modules must follow this convention.
