# Copyright (c) 2020-2025 ITER Organization,
#               CS 90046
#               13067 St Paul Lez Durance Cedex
#               France
# Author IO
#
# This file is part of iplotlib module.
# iplotlib python module is free software: you can redistribute it and/or modify it under
# the terms of the MIT license.
#
# This file is part of ITER CODAC software.
# For the terms and conditions of redistribution or use of this software
# refer to the file LICENSE located in the top level directory
# of the distribution package
#


"""
Serialization inventory for iplotlib core classes.
"""

import dataclasses
import json
from json import JSONEncoder
from typing import Dict, List

import numpy as np

from iplotLogging import setupLogger

logger = setupLogger.get_logger(__name__)


class JSONExporter:
    """
    This class exports/imports nested @dataclasses structure from and to JSON format.
    In order to preserve correct types for collection items the type name is additionally saved in '_type' property
    """

    TYPE_ALIASES = {
        "iplotlib.Canvas.Canvas": "iplotlib.core.canvas.Canvas",
        "iplotlib.Plot.Plot2D": "iplotlib.core.plot.PlotXY",
        "iplotlib.Axis.LinearAxis": "iplotlib.core.axis.LinearAxis",
        "iplotlib.Signal.UDAPulse": "iplotlib.interface.iplotSignalAdapter.IplotSignalAdapter",
        "iplotlib.interface.iplotSignalAdapter.IplotSignalAdapter": "iplotlib.core.signal.SignalXY",
    }

    def to_dict(self, obj):
        return json.loads(self.to_json(obj))

    def from_dict(self, inp_dict):
        return self.dataclass_from_dict(inp_dict)

    @staticmethod
    def to_json(obj):
        return json.dumps(obj, cls=DataclassNumpyJSONEncoder, indent=4)

    def from_json(self, string):
        return self.from_dict(json.loads(string))

    @staticmethod
    def make_compatible(d, klass):
        from iplotlib.core.signal import Signal
        if issubclass(klass, Signal):
            try:
                label = d.pop('title')
                d.update({'label': label})
            except KeyError:
                pass

    def dataclass_from_dict(self, d, klass=None):
        """
        Creates a dataclass instance from nested dicts. If dict has a _type key then this value
        is used as a dataclass base class
        """

        def create_klass(kls: str):
            parts = kls.split('.')
            m = __import__(".".join(parts[:-1]))
            for comp in parts[1:]:
                m = getattr(m, comp)
            return m

        def create_klass_using_aliases(kls: str):
            type_alias = self.TYPE_ALIASES.get(kls)
            return create_klass(kls) if type_alias is None else create_klass(type_alias)

        if isinstance(d, Dict):
            if d.get("_type") is not None:
                klass = create_klass_using_aliases(d.get("_type"))
                self.make_compatible(d, klass)
            else:
                return {k: self.dataclass_from_dict(v) for (k, v) in d.items()}

        if isinstance(d, List):
            return [self.dataclass_from_dict(e) for e in d]

        if dataclasses.is_dataclass(klass):
            try:
                field_types = {f.name: f.type for f in dataclasses.fields(klass)}
                return klass(**{f: self.dataclass_from_dict(d[f], field_types[f]) for f in d if f in field_types})
            except Exception as e:
                logger.error(f"Error: {e}")
                return d
        else:
            return d


class DataclassNumpyJSONEncoder(JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        if isinstance(o, np.integer):
            return int(o)
        elif isinstance(o, np.floating):
            return float(o)
        elif isinstance(o, np.ndarray):
            return o.tolist()
        return super().default(o)
