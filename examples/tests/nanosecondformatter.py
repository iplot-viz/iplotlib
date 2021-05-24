import sys
import traceback
from functools import partial

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.dates import AutoDateLocator
from matplotlib.scale import LinearScale, ScaleBase
from matplotlib.ticker import AutoLocator, FixedLocator, LinearLocator, MultipleLocator, NullLocator, ScalarFormatter
from matplotlib.transforms import Affine2D, IdentityTransform, ScaledTranslation, Transform, nonsingular
from matplotlib.units import registry
from numpy import float64, ndarray
from pandas.plotting import register_matplotlib_converters
from matplotlib.scale import register_scale

from iplotlib.impl.matplotlib.dateFormatter import NanosecondDateFormatter


class AutoNanoLocator(FixedLocator):

    def __call__(self):
        r = super().tick_values(None, None)
        print("R",r)
        return r

    def nonsingular(self, v0, v1):
        print("NONSINGULAR", v0, v1)
        return v0, v1


class OffsetScale(ScaleBase):
    name = 'offset'

    def __init__(self, axis, **kwargs):
        self.offset = kwargs.get('offset')
        super().__init__(axis, **kwargs)

    def get_transform(self):
        return OffsetTransform(self.offset)

    def set_default_locators_and_formatters(self, axis):
        axis.set_major_formatter(NanosecondDateFormatter())
        axis.set_major_locator(AutoNanoLocator())
        pass


class OffsetTransform(Transform):
    input_dims = output_dims = 1

    def __init__(self, offset):
        Transform.__init__(self)
        self.offset = offset

    def transform_non_affine(self, values):
        print("Transform [{}] : {} -> {}".format(self.offset, values, values - self.offset))
        return values - self.offset

    def inverted(self):
        return OffsetTransform(-self.offset)


def date_axis():
    register_matplotlib_converters()
    register_scale(OffsetScale)

    x = np.array(['2020-12-11T11:26:37.000000000', '2020-12-14T11:26:37.200000000', '2020-12-14T11:26:37.400000000', '2020-12-14T11:26:37.600000000', '2020-12-14T11:26:37.800000000',
                  '2020-12-14T11:26:38.000000000', '2020-12-14T11:26:38.200000000', '2020-12-14T11:26:38.400000000', '2020-12-14T11:26:38.600000000', '2020-12-14T11:26:38.800000000'],
                 dtype="datetime64[ns]")
    y = np.array([7675.92578125, 7666.66650391, 7675.92578125, 7666.66650391, 7675.92578125, 7666.66650391, 7675.92578125, 7685.18505859, 7675.92578125, 7666.66650391])

    x = np.array(['2020-12-14T10:26:00.000000100', '2020-12-14T10:26:00.000000120', '2020-12-14T10:26:00.000000200'], dtype="datetime64[ns]")
    y = np.array([5, 12, 10])

    x = x.astype('int64')

    print(x)

    def forward(offset, values):
        return values - offset

    def inverse(offset, values):
        return values + offset

    def funcFormatter(val, pos):
        # print(F"DEBUG: funcformatter {val}")
        # return f'[{val:.2f}]'
        return "x{}".format(val)[-4:]

    ax = plt.subplot()

    # x -= x[0]

    l = x[0]
    r = x[-1]

    print("L/R", l, r)
    # l, r = nonsingular(x[0], x[-1])
    # ax.set_xscale('offset', offset=l)
    ax.set_xscale("function", functions=(partial(forward, l), partial(inverse, l)))
    ax.xaxis.set_major_formatter(funcFormatter)
    ax.xaxis.set_major_locator(AutoNanoLocator(x))
    # ax.xaxis.set_major_locator(FixedLocator(x))
    ax.set_xlim(left=l, right=r)
    # ax.set_xlim(left=1607941560000000000, right=1607941560000005000)

    # ax.margins(1)
    ax.set_autoscalex_on(False)

    plt.plot(x, y)

    plt.show()

    # print(ax.get_xaxis_transform().transform([1607941560000000100, 0]))
    # print(ax.get_xaxis_transform().transform([1607941560000000120, 0]))
    # print(ax.get_xaxis_transform().transform([1607941560000000200, 0]))
    print("L/R", l, r)

    # print(ax.transData.transform((1607941560000000100, 8)))
    # print(ax.transData.transform((1607941560000000120, 8)))
    # print(ax.transData.transform((1607941560000000200, 8)))

    ax.transLimits

    # for t in [ax.transLimits]:
    #     print(F"TRANSFORM",t)
    #     print(["{:.20f}".format(e) for e in t.transform((x[0], y[0]))])
    #     print(["{:.20f}".format(e) for e in t.transform((x[1], y[1]))])
    #     print(["{:.20f}".format(e) for e in t.transform((x[2], y[2]))])

    # print(["{:.20f}".format(e) for e in ax.transData.inverted().transform((640, 480))])

    limittransformedbbox = ax.transLimits._boxin
    bbox = limittransformedbbox._bbox
    bboxtransform = limittransformedbbox._transform
    bboxpoints = limittransformedbbox._points


    # print(F"TransLimits transform: BboxTransformFrom: mtx={ax.transLimits._mtx} boxin={limittransformedbbox}")

    print(F"LLL bbox={bbox} transform={bboxtransform} points={bboxpoints}")
    print(F"\tBBOX: x0={bbox.x0} x1={bbox.x1}")

date_axis()
