#!/usr/bin/env python
# coding: utf8
"""
Train a convolutional neural network for multilabel classification
of grants
Adapted from https://github.com/explosion/spaCy/blob/master/examples/training/train_textcat.py
"""
from spacy.util import minibatch, compounding, decaying
from sklearn.metrics import f1_score, precision_score, recall_score
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.model_selection import train_test_split
from sklearn.metrics import precision_recall_fscore_support
import numpy as np
import spacy
import torch

import random

from wellcomeml.logger import logger

is_using_gpu = spacy.prefer_gpu()
if is_using_gpu:
    torch.set_default_tensor_type("torch.cuda.FloatTensor")


class SpacyClassifier(BaseEstimator, ClassifierMixin):
    def __init__(self, threshold=0.5, n_iterations=5,
                 batch_size=8, learning_rate=0.001, dropout=0.1):
        self.threshold = threshold
        self.batch_size = batch_size
        self.dropout = dropout
        self.learning_rate = learning_rate
        self.n_iterations=n_iterations

    def _init_nlp(self):
        self.nlp = spacy.blank('en')

        # Add a param for exclusive classes to cover non multilabel
        self.textcat = self.nlp.create_pipe(
            "textcat",
            config={
                "exclusive_classes": False,
                "architecture": "simple_cnn",
            }
        )
        self.nlp.add_pipe(self.textcat, last=True)

        for label in self.unique_labels:
            self.textcat.add_label(label)

    def load(self, model_dir):
        self.nlp = spacy.load(model_dir)
        # another hack to get the labels from textcat since
        # spacy does not serialise every attribute
        for pipe_name, pipe in self.nlp.pipeline:
            # to cover case of textcat and trf_textcat
            if 'textcat' in pipe_name:
                self.unique_labels = pipe.labels

    def save(self, output_dir):
        self.nlp.to_disk(output_dir)

    def _label_binarizer_inverse_transform(self, Y_train):
        "Transforms Y matrix to labels which are the non zero indices"
        data = []
        for row in Y_train:
            row_data = [str(i) for i, item in enumerate(row) if item]
            data.append(row_data)
        # Do we need to convert to numpy?
        return np.array(data)

    def fit(self, X, Y):
        """
        Args:
            X: 1d list of documents
            Y: 2d numpy array (nb_examples, nb_labels)
        TODO: Generalise to y being 1d
        """
        Y = np.array(Y)

        X_train, X_test, Y_train, Y_test = train_test_split(
            X, Y, random_state=42
        )

        nb_labels = Y_train.shape[1]
        self.unique_labels = [str(i) for i in range(nb_labels)]
        self._init_nlp()
        n_iter = self.n_iterations
        train_texts = X_train
        train_tags = self._label_binarizer_inverse_transform(Y_train)
    
        train_cats = [
            {
                label: label in tags
                for label in self.unique_labels
            } for tags in train_tags
        ]

        train_data = list(zip(train_texts, [{"cats": cats} for cats in train_cats]))

        other_pipes = [pipe for pipe in self.nlp.pipe_names if pipe != "textcat"]
        with self.nlp.disable_pipes(*other_pipes):  # only train textcat
            optimizer = self.nlp.begin_training()
            optimizer.alpha = self.learning_rate
            #optimizer.L2 = 1e-4
            logger.info("Training the model...")
            logger.info("{:^5}\t{:^5}\t{:^5}\t{:^5}\t{:^5}".format("ITER", "LOSS", "P", "R", "F"))
            batch_sizes = compounding(4.0, self.batch_size, 1.001)
            #dropout = decaying(0.6, 0.2, 1e-4)
            for i in range(n_iter):
                losses = {}
                # batch up the examples using spaCy's minibatch
                random.shuffle(train_data)
                batches = minibatch(train_data, size=batch_sizes)
                for batch in batches:
                    texts, annotations = zip(*batch)
                    next_dropout = self.dropout # next(dropout)
                    self.nlp.update(texts, annotations, sgd=optimizer, drop=next_dropout, losses=losses)
                with self.textcat.model.use_params(optimizer.averages):
                    Y_train_pred = self.predict(X_train)
                    Y_test_pred = self.predict(X_test)
                    p, r, f, _ = precision_recall_fscore_support(Y_test, Y_test_pred, average='micro')
                loss = losses["textcat"]
                logger.info(
                    "{0:2d}\t{1:.3f}\t{2:.3f}\t{3:.3f}\t{4:.3f}".format(
                        i,
                        loss,
                        p,
                        r,
                        f
                    )
                )
        return self

    def predict(self, X):
        def binarize_output(x):
            cats = self.nlp(x).cats
            out = [
                1 if cats[label] > self.threshold else 0
                for label in self.unique_labels
            ]
            return out

        return np.array([binarize_output(x) for x in X])

    def predict_proba(self, X):
        def get_proba(x):
            cats = self.nlp(x).cats
            out = [
                cats[label]
                for label in self.unique_labels
            ]
            return out
        return np.array([get_proba(x) for x in X])

    def score(self, X, Y):
        Y = np.array(Y)
        Y_pred = self.predict(X)
        return f1_score(Y_pred, Y, average='micro')
