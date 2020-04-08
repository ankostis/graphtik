# Copyright 2016, Yahoo Inc.
# Licensed under the terms of the Apache License, Version 2.0. See the LICENSE file associated with the project for terms.
"""
Generic or specific utilities  without polluting imports.

.. testsetup::

    from graphtik.base import *
"""

import abc
import logging
from collections import defaultdict, namedtuple
from functools import partial, partialmethod, wraps
from typing import Any, Collection, List, Mapping, Optional, Tuple, Union

Items = Union[Collection, str, None]

log = logging.getLogger(__name__)


class MultiValueError(ValueError):
    def __str__(self):
        """Assuming it has been called with ``MultiValueError(msg, ex1, ...) #"""
        return str(self.args[0])  # pylint: disable=unsubscriptable-object


class Token(str):
    """Guarantee equality, not(!) identity, across processes."""

    __slots__ = ("hashid",)

    def __new__(cls, s):
        return super().__new__(cls, f"<{s}>")

    def __init__(self, *args):
        import random

        self.hashid = random.randint(-(2 ** 32), 2 ** 32 - 1)

    def __eq__(self, other):
        return self.hashid == getattr(other, "hashid", None)

    def __hash__(self):
        return self.hashid

    def __getstate__(self):
        return self.hashid

    def __setstate__(self, state):
        self.hashid = state

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __bool__(self):
        """Always `True`, even if empty string."""
        return True

    def __repr__(self):
        """Avoid 'ticks' around repr."""
        return self.__str__()


#: When an operation function returns this special value,
#: it implies operation has no result at all,
#: (otherwise, it would have been a single result, ``None``).`
NO_RESULT = Token("NO_RESULT")
UNSET = Token("UNSET")


def aslist(i, argname, allowed_types=list):
    """Utility to accept singular strings as lists, and None --> []."""
    if not i:
        return i if isinstance(i, allowed_types) else []

    if isinstance(i, str):
        i = [i]
    elif not isinstance(i, allowed_types):
        try:
            i = list(i)
        except Exception as ex:
            raise ValueError(f"Cannot list-ize {argname}({i!r}) due to: {ex}") from None

    return i


def astuple(i, argname, allowed_types=tuple):
    if not i:
        return i if isinstance(i, allowed_types) else ()

    if isinstance(i, str):
        i = (i,)
    elif not isinstance(i, allowed_types):
        try:
            i = tuple(i)
        except Exception as ex:
            raise ValueError(
                f"Cannot tuple-ize {argname}({i!r}) due to: {ex}"
            ) from None

    return i


def jetsam(ex, locs, *salvage_vars: str, annotation="jetsam", **salvage_mappings):
    """
    Annotate exception with salvaged values from locals() and raise!

    :param ex:
        the exception to annotate
    :param locs:
        ``locals()`` from the context-manager's block containing vars
        to be salvaged in case of exception

        ATTENTION: wrapped function must finally call ``locals()``, because
        *locals* dictionary only reflects local-var changes after call.
    :param annotation:
        the name of the attribute to attach on the exception
    :param salvage_vars:
        local variable names to save as is in the salvaged annotations dictionary.
    :param salvage_mappings:
        a mapping of destination-annotation-keys --> source-locals-keys;
        if a `source` is callable, the value to salvage is retrieved
        by calling ``value(locs)``.
        They take precedence over`salvage_vars`.

    :raises:
        any exception raised by the wrapped function, annotated with values
        assigned as attributes on this context-manager

    - Any attributes attached on this manager are attached as a new dict on
      the raised exception as new  ``jetsam`` attribute with a dict as value.
    - If the exception is already annotated, any new items are inserted,
      but existing ones are preserved.

    **Example:**

    Call it with managed-block's ``locals()`` and tell which of them to salvage
    in case of errors::


        try:
            a = 1
            b = 2
            raise Exception()
        exception Exception as ex:
            jetsam(ex, locals(), "a", b="salvaged_b", c_var="c")
            raise

    And then from a REPL::

        import sys
        sys.last_value.jetsam
        {'a': 1, 'salvaged_b': 2, "c_var": None}

    ** Reason:**

    Graphs may become arbitrary deep.  Debugging such graphs is notoriously hard.

    The purpose is not to require a debugger-session to inspect the root-causes
    (without precluding one).

    Naively salvaging values with a simple try/except block around each function,
    blocks the debugger from landing on the real cause of the error - it would
    land on that block;  and that could be many nested levels above it.
    """
    ## Fail EARLY before yielding on bad use.
    #
    assert isinstance(ex, Exception), ("Bad `ex`, not an exception dict:", ex)
    assert isinstance(locs, dict), ("Bad `locs`, not a dict:", locs)
    assert all(isinstance(i, str) for i in salvage_vars), (
        "Bad `salvage_vars`!",
        salvage_vars,
    )
    assert salvage_vars or salvage_mappings, "No `salvage_mappings` given!"
    assert all(isinstance(v, str) or callable(v) for v in salvage_mappings.values()), (
        "Bad `salvage_mappings`:",
        salvage_mappings,
    )

    ## Merge vars-mapping to save.
    for var in salvage_vars:
        if var not in salvage_mappings:
            salvage_mappings[var] = var

    try:
        annotations = getattr(ex, annotation, None)
        if not isinstance(annotations, dict):
            annotations = {}
            setattr(ex, annotation, annotations)

        ## Salvage those asked
        for dst_key, src in salvage_mappings.items():
            try:
                salvaged_value = src(locs) if callable(src) else locs.get(src)
                annotations.setdefault(dst_key, salvaged_value)
            except Exception as ex:
                log.warning(
                    "Suppressed error while salvaging jetsam item (%r, %r): %r"
                    % (dst_key, src, ex)
                )
    except Exception as ex2:
        log.warning("Suppressed error while annotating exception: %r", ex2, exc_info=1)
        raise ex2


## Defined here, to avoid subclasses importing `plot` module.
class Plottable(abc.ABC):
    """
    Classes wishing to plot their graphs should inherit this and ...

    implement property ``plot`` to return a "partial" callable that somehow
    ends up calling  :func:`.plot.render_pydot()` with the `graph` or any other
    args bound appropriately.
    The purpose is to avoid copying this function & documentation here around.
    """

    def plot(
        self,
        filename=None,
        show=False,
        jupyter_render: Union[None, Mapping, str] = None,
        **kws,
    ) -> "pydot.Dot":
        """
        Entry-point for plotting ready made operation graphs.

        :param str graph:
            (optional) An :class:`nx.Digraph` usually provided by underlying plottables.
            It may contain graph, node & edge attributes for the plotting methods,
            eventually reaching `Graphviz`_, among others:

            _name (graph)
                if given, dot-lang graph would not be named "G"; necessary to be unique
                when referring to generated CMAPs.
                Note that it is "private", not to convey to DOT file.

            .. Note::
                Remember to properly escape values for `Graphviz`_
                e.g. with :func:`html.escape()` or :func:`.plot.quote_dot_word()`.

        :param str filename:
            Write diagram into a file.
            Common extensions are ``.png .dot .jpg .jpeg .pdf .svg``
            call :func:`plot.supported_plot_formats()` for more.
        :param show:
            If it evaluates to true, opens the  diagram in a  matplotlib window.
            If it equals `-1`, it plots but does not open the Window.
        :param inputs:
            an optional name list, any nodes in there are plotted
            as a "house"
        :param outputs:
            an optional name list, any nodes in there are plotted
            as an "inverted-house"
        :param solution:
            an optional dict with values to annotate nodes, drawn "filled"
            (currently content not shown, but node drawn as "filled").
            It extracts more infos from a :class:`.Solution` instance, such as,
            if `solution` has an ``executed`` attribute, operations contained in it
            are  drawn as "filled".
        :param clusters:
            an optional mapping of nodes --> cluster-names, to group them
        :param splines:
            Whether to plot `curved/polyline edges
            <https://graphviz.gitlab.io/_pages/doc/info/attrs.html#d:splines>`_
            [default: "ortho"]
        :param jupyter_render:
            a nested dictionary controlling the rendering of graph-plots in Jupyter cells,
            if `None`, defaults to :data:`jupyter_render`; you may modify it in place
            and apply for all future calls (see :ref:`jupyter_rendering`).
        :param legend_url:
            a URL to the *graphtik* legend; if it evaluates to false, none is added.

        :return:
            a |pydot.Dot|_ instance
            (for reference to as similar API to |pydot.Dot|_ instance, visit:
            https://pydotplus.readthedocs.io/reference.html#pydotplus.graphviz.Dot)

            The |pydot.Dot|_ instance returned is rendered directly in *Jupyter/IPython*
            notebooks as SVG images (see :ref:`jupyter_rendering`).

        Note that the `graph` argument is absent - Each Plottable provides
        its own graph internally;  use directly :func:`.render_pydot()` to provide
        a different graph.

        .. image:: images/GraphtikLegend.svg
            :alt: Graphtik Legend

        *NODES:*

        oval
            function
        egg
            subgraph operation
        house
            given input
        inversed-house
            asked output
        polygon
            given both as input & asked as output (what?)
        square
            intermediate data, neither given nor asked.
        red frame
            evict-instruction, to free up memory.
        filled
            data node has a value in `solution` OR function has been executed.
        thick frame
            function/data node in execution `steps`.

        *ARROWS*

        solid black arrows
            dependencies (source-data *need*-ed by target-operations,
            sources-operations *provides* target-data)
        dashed black arrows
            optional needs
        blue arrows
            sideffect needs/provides
        wheat arrows
            broken dependency (``provide``) during pruning
        green-dotted arrows
            execution steps labeled in succession


        To generate the **legend**, see :func:`.legend()`.

        **Sample code:**

        >>> from graphtik import compose, operation
        >>> from graphtik.modifiers import optional
        >>> from operator import add

        >>> netop = compose("netop",
        ...     operation(name="add", needs=["a", "b1"], provides=["ab1"])(add),
        ...     operation(name="sub", needs=["a", optional("b2")], provides=["ab2"])(lambda a, b=1: a-b),
        ...     operation(name="abb", needs=["ab1", "ab2"], provides=["asked"])(add),
        ... )

        >>> netop.plot(show=True);                 # plot just the graph in a matplotlib window # doctest: +SKIP
        >>> inputs = {'a': 1, 'b1': 2}
        >>> solution = netop(**inputs)             # now plots will include the execution-plan

        >>> netop.plot('plot1.svg', inputs=inputs, outputs=['asked', 'b1'], solution=solution);           # doctest: +SKIP
        >>> dot = netop.plot(solution=solution);   # just get the `pydot.Dot` object, renderable in Jupyter
        >>> print(dot)
        digraph netop {
        fontname=italic;
        label=<netop>;
        splines=ortho;
        <a> [fillcolor=wheat, shape=invhouse, style=filled, tooltip=<(int) 1>];
        ...

        """
        from .plot import render_pydot

        dot = self._build_pydot(**kws)
        return render_pydot(
            dot, filename=filename, show=show, jupyter_render=jupyter_render
        )

    @abc.abstractmethod
    def _build_pydot(self, **kws):
        pass


def func_name(fn, default=..., mod=None, fqdn=None, human=None) -> Optional[str]:
    """
    FQDN of `fn`, descending into partials to print their args.

    :param default:
        What to return if it fails; by default it raises.
    :param mod:
        when true, prepend module like ``module.name.fn_name``
    :param fqdn:
        when true, use ``__qualname__`` (instead of ``__name__``)
        which differs mostly on methods, where it contains class(es),
        and locals, respectively (:pep:`3155`).
        *Sphinx* uses `fqdn=True` for generating IDs.
    :param human:
        when true, partials denote their args like ``fn({"a": 1}, ...)`` in the returned text,
        otherwise, just the (fqd-)name, appropriate for IDs.

    :return:
        a (possibly dot-separated) string, or `default` (unless this is ``...```).
    :raises:
        Only if default is ``...``, otherwise, errors debug-logged.


    **Examples**

        >>> func_name(func_name)
        'func_name'
        >>> func_name(func_name, mod=1)
        'graphtik.base.func_name'
        >>> func_name(MultiValueError.mro, fqdn=0)
        'mro'
        >>> func_name(MultiValueError.mro, fqdn=1)
        'MultiValueError.mro'

    Even functions defined in docstrings are reported:

        >>> def f():
        ...     def inner():
        ...         pass
        ...     return inner

        >>> func_name(f, mod=1, fqdn=1)
        'graphtik.base.f'
        >>> func_name(f(), fqdn=1)
        'f.<locals>.inner'

    On failures, arg `default` controls the outcomes:

    TBD
    """
    if isinstance(fn, (partial, partialmethod)):
        # Always bubble-up errors.
        fn_name = func_name(fn.func, default, mod, fqdn, human)
        if human:
            args = [str(i) for i in (fn.args, fn.keywords) if i]
            args.append("...")
            args_str = ", ".join(args)
            fn_name = f"{fn_name}({args_str})"

        return fn_name

    try:
        fn_name = fn.__qualname__ if fqdn else fn.__name__
        assert fn_name

        mod_name = getattr(fn, "__module__", None)
        if mod and mod_name:
            fn_name = ".".join((mod_name, fn_name))
        return fn_name
    except Exception as ex:
        if default is ...:
            raise
        log.debug(
            "Ignored error while inspecting %r name: %s", fn, ex,
        )
        return default


def _un_partial_ize(func):
    """
    Alter functions working on 1st arg being a callable, to descend it if it's a partial.
    """

    @wraps(func)
    def wrapper(fn, *args, **kw):
        if isinstance(fn, (partial, partialmethod)):
            return func(fn.func, *args, **kw)
        return func(fn, *args, **kw)

    return wrapper


@_un_partial_ize
def func_source(fn, default=..., human=None) -> Optional[Tuple[str, int]]:
    """
    Like :func:`inspect.getsource` supporting partials.

    :param default:
        If given, better be a 2-tuple respecting types,
        or ``...``, to raise.
    :param human:
        when true, partials denote their args like ``$fn(a=1, ...)`` in the returned text,
        otherwise, just the (fqd-)name, appropriate for IDs.
    """
    import inspect

    try:
        if human and inspect.isbuiltin(fn):
            return str(fn)
        return inspect.getsource(fn)
    except Exception as ex:
        if default is ...:
            raise
        log.debug(
            "Ignored error while inspecting %r sources: %s", fn, ex,
        )
        return default


@_un_partial_ize
def func_sourcelines(fn, default=..., human=None) -> Optional[Tuple[str, int]]:
    """
    Like :func:`inspect.getsourcelines` supporting partials.

    :param default:
        If given, better be a 2-tuple respecting types,
        or ``...``, to raise.
    """
    import inspect

    try:
        if human and inspect.isbuiltin(fn):
            return [str(fn)], -1
        return inspect.getsourcelines(fn)
    except Exception as ex:
        if default is ...:
            raise
        log.debug(
            "Ignored error while inspecting %r sourcelines: %s", fn, ex,
        )
        return default


def graphviz_html_string(s):
    import html

    if s:
        s = html.escape(s).replace("\n", "&#10;")
        s = f"<{s}>"
    return s


PlotArgs = namedtuple("PlotArgs", "graph, steps, inputs, outputs, solution, clusters")
"""All the args of a :meth:`.Plottable.plot()` call. """


def default_plot_annotator(
    plot_args: PlotArgs, url_fmt: str = None, link_target: str = None,
) -> None:
    """
    Annotate DiGraph to be plotted with doc URLs, and code & solution tooltips.

    :param plot_args:
        as passed in :meth:`.plot()`.
    :param url_fmt:
        a ``%s``-format string accepting the function-path used to form the final URL
        of the node; if it evaluates to false (default), no URL added.
    :param link_target:
        if given, adds a graphviz target attribute to control where to open
        the url (e.g. ``_blank`` or ``_top``)

    Override it with :func:`.config.nx_network_annotator` or
    :func:`.config.set_nx_network_annotator`.

    .. Note::
        - SVG tooltips may not work without URL on PDFs:
          https://gitlab.com/graphviz/graphviz/issues/1425

        - Browsers & Jupyter lab are blocking local-urls (e.g. on SVGs),
          see tip in :term:`plottable`.
    """
    from .op import Operation

    nx_net = plot_args.graph
    for nx_node, node_attrs in nx_net.nodes.data():
        tooltip = None
        if isinstance(nx_node, Operation):
            if url_fmt and "URL" not in node_attrs:
                fn_path = func_name(nx_node.fn, None, mod=1, fqdn=1, human=0)
                if fn_path:
                    url = url_fmt % fn_path
                    node_attrs["URL"] = graphviz_html_string(url)
                    if link_target:
                        node_attrs["target"] = link_target

            if "tooltip" not in node_attrs:
                fn_source = func_source(nx_node.fn, None, human=1)
                if fn_source:
                    node_attrs["tooltip"] = graphviz_html_string(fn_source)
        else:  # DATA node
            sol = plot_args.solution
            if sol is not None and "tooltip" not in node_attrs:
                val = sol.get(nx_node)
                tooltip = "None" if val is None else f"({type(val).__name__}) {val}"
                node_attrs["tooltip"] = graphviz_html_string(tooltip)
