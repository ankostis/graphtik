# Copyright 2016, Yahoo Inc.
# Licensed under the terms of the Apache License, Version 2.0. See the LICENSE file associated with the project for terms.

import pytest

from graphtik import operation
from graphtik.op import Operation, reparse_operation_data


@pytest.fixture(params=[None, ["some"]])
def opname(request):
    return request.param


@pytest.fixture(params=[None, ["some"]])
def opneeds(request):
    return request.param


@pytest.fixture(params=[None, ["some"]])
def opprovides(request):
    return request.param


class MyOp(Operation):
    def compute(self):
        pass


def test_operation_repr(opname, opneeds, opprovides):
    # Simply check __repr__() does not crash on partial attributes.
    kw = locals().copy()
    kw = {name[2:]: arg for name, arg in kw.items()}

    op = operation(**kw)
    str(op)

    op = MyOp(**kw)
    str(op)


@pytest.mark.parametrize(
    "opargs, exp",
    [
        ((None, None, None), ValueError("Empty `needs`")),
        (("_", "a", "A"), ("_", ["a"], ["A"])),
        (((), "a", None), ((), ["a"], ())),
        ((("a",), "a", "b"), (("a",), ["a"], ["b"])),
    ],
)
def test_operation_validation(opargs, exp):
    if isinstance(exp, Exception):
        with pytest.raises(type(exp), match=str(exp)):
            reparse_operation_data(*opargs)
    else:
        assert reparse_operation_data(*opargs) == exp
