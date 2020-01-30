# encoding: utf-8

import numpy as np

from wellcomeml.ml import BertClassifier

def test_multilabel():
    X = [
        "One and two",
        "One only",
        "Three and four, nothing else",
        "Two nothing else",
        "Two and three"
    ]
    Y = np.array([
        [1,1,0,0],
        [1,0,0,0],
        [0,0,1,1],
        [0,1,0,0],
        [0,1,1,0]
    ])

    model = BertClassifier()
    model.fit(X, Y)
    assert model.score(X, Y) > 0.4
    assert model.predict(X).shape == (5,4)