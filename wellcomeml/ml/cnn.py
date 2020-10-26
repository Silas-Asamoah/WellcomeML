"""
CNN architecture inspired from spacy for NLP tasks

It follows the embed, encode, attend, predict framework

    Embed: learns a new embedding but can receive
    pre trained embeddings as well

    Encode: stacked CNN with context window 3 that maintains the size of input and applies dropout
    and layer norm

    Attend: not yet implemented

    Predict: softmax or sigmoid depending on number of outputs
    and whether task is multilabel
"""
from datetime import datetime
import math

from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.model_selection import train_test_split
from sklearn.metrics import f1_score
from scipy.sparse import csr_matrix, vstack
import tensorflow as tf
import numpy as np

from wellcomeml.ml.attention import HierarchicalAttention

TENSORBOARD_LOG_DIR = "logs/scalar/" + datetime.now().strftime("%Y%m%d-%H%M%S")
CALLBACK_DICT = {
    'tensorboard': tf.keras.callbacks.TensorBoard(log_dir=TENSORBOARD_LOG_DIR)
}


class CNNClassifier(BaseEstimator, ClassifierMixin):
    def __init__(
        self,
        context_window=3,
        learning_rate=0.001,
        learning_rate_decay=1,
        batch_size=32,
        nb_epochs=5,
        dropout=0.2,
        nb_layers=4,
        hidden_size=100,
        l2=1e-6,
        dense_size=32,
        multilabel=False,
        attention=False,
        attention_heads='same',
        metrics=["precision", "recall"],
        callbacks=["tensorboard"],
        feature_approach="max",
        early_stopping=False,
        sparse_y=False
    ):
        self.context_window = context_window
        self.learning_rate = learning_rate
        self.learning_rate_decay = learning_rate_decay
        self.batch_size = batch_size
        self.nb_epochs = nb_epochs
        self.dropout = dropout
        self.nb_layers = nb_layers
        # note that on current implementation CNN use same hidden size as embedding
        # so if embedding matrix is passed, this is not used. in the future we can decouple
        self.hidden_size = hidden_size
        self.l2 = l2
        self.dense_size = dense_size
        self.multilabel = multilabel
        self.attention = attention
        self.attention_heads = attention_heads
        self.metrics = metrics
        self.callbacks = callbacks
        self.feature_approach = feature_approach
        self.early_stopping = early_stopping
        self.sparse_y = sparse_y

    def _yield_data(self, X, Y, batch_size, shuffle=True):
        while True:
            if shuffle:
                randomize = np.arange(len(X))
                np.random.shuffle(randomize)
                X = X[randomize]
                Y = Y[randomize]
            for i in range(0, X.shape[0], batch_size):
                X_batch = X[i:i+batch_size, :]
                Y_batch = Y[i:i+batch_size, :]
                if self.sparse_y:
                    Y_batch = Y_batch.todense()
                yield X_batch, Y_batch

    def _build_model(self, sequence_length, vocab_size, nb_outputs,
                     steps_per_epoch, embedding_matrix=None,
                     metrics=["precision", "recall"]):
        def residual_conv_block(x1, l2):
            filters = x1.shape[2]
            x2 = tf.keras.layers.Conv1D(
                filters,
                self.context_window,
                padding="same",
                activation="relu",
                kernel_regularizer=l2,
            )(x1)
            x2 = tf.keras.layers.Dropout(self.dropout)(x2)
            x2 = tf.keras.layers.LayerNormalization()(x2)
            return tf.keras.layers.add([x1, x2])

        def residual_attention(x1):
            x2 = HierarchicalAttention(self.attention_heads)(x1)
            x2 = tf.keras.layers.Dropout(self.dropout)(x2)
            x2 = tf.keras.layers.LayerNormalization()(x2)
            if self.attention_heads == 'same':
                return tf.keras.layers.add([x1, x2])
            else:
                return x2

        METRIC_DICT = {
            'precision': tf.keras.metrics.Precision(name='precision'),
            'recall': tf.keras.metrics.Recall(name='recall'),
            'auc': tf.keras.metrics.AUC(name='auc')
        }

        embeddings_initializer = (
            tf.keras.initializers.Constant(embedding_matrix)
            if embedding_matrix
            else "uniform"
        )
        emb_dim = embedding_matrix.shape[1] if embedding_matrix else self.hidden_size

        l2 = tf.keras.regularizers.l2(self.l2)
        inp = tf.keras.layers.Input(shape=(sequence_length,))
        x = tf.keras.layers.Embedding(
            vocab_size,
            emb_dim,
            input_length=sequence_length,
            embeddings_initializer=embeddings_initializer,
        )(inp)
        x = tf.keras.layers.Dropout(
            self.dropout,
            noise_shape=(None, sequence_length, 1))(x)
        x = tf.keras.layers.LayerNormalization()(x)
        for i in range(self.nb_layers):
            x = residual_conv_block(x, l2)
        if self.attention:
            x = residual_attention(x)
        if self.feature_approach == 'max':
            x = tf.keras.layers.GlobalMaxPooling1D()(x)
        elif self.feature_approach == 'sum':
            x = tf.keras.backend.sum(x, axis=1)
        elif self.feature_approach == 'concat':
            x = tf.concat(x, axis=1)
        else:
            raise NotImplementedError
        x = tf.keras.layers.Dense(
            self.dense_size, activation="relu", kernel_regularizer=l2
        )(x)
        x = tf.keras.layers.Dropout(self.dropout)(x)
        x = tf.keras.layers.LayerNormalization()(x)

        output_activation = (
            "sigmoid" if nb_outputs == 1 or self.multilabel else "softmax"
        )
        out = tf.keras.layers.Dense(
            nb_outputs,
            activation=output_activation,
            kernel_regularizer=l2,
        )(x)
        model = tf.keras.Model(inp, out)

        learning_rate = tf.keras.optimizers.schedules.ExponentialDecay(
            self.learning_rate, steps_per_epoch, self.learning_rate_decay,
            staircase=True
        )
        strategy = tf.distribute.get_strategy()
        if isinstance(strategy, tf.distribute.MirroredStrategy):
            optimizer = tf.keras.optimizers.Adam(learning_rate)
        else:  # clipnorm is only supported in default strategy
            optimizer = tf.keras.optimizers.Adam(learning_rate, clipnorm=1.0)
        metrics = [
            METRIC_DICT[m] if m in METRIC_DICT else m
            for m in metrics
        ]
        model.compile(optimizer=optimizer, loss="binary_crossentropy", metrics=metrics)
        return model

    def fit(self, X, Y, embedding_matrix=None):
        sequence_length = X.shape[1]
        vocab_size = X.max() + 1
        nb_outputs = Y.max() if not self.multilabel else Y.shape[1]

        X_train, X_val, Y_train, Y_val = train_test_split(
            X, Y, test_size=0.1, shuffle=True
        )
        steps_per_epoch = math.ceil(X_train.shape[0] / self.batch_size)
        validation_steps = math.ceil(X_val.shape[0] / self.batch_size)

        if tf.config.list_physical_devices('GPU'):
            strategy = tf.distribute.MirroredStrategy()
        else:  # use default strategy
            strategy = tf.distribute.get_strategy()
        with strategy.scope():
            self.model = self._build_model(
                sequence_length, vocab_size, nb_outputs,
                steps_per_epoch, embedding_matrix)

        callbacks = [
            CALLBACK_DICT[c] if c in CALLBACK_DICT else c
            for c in self.callbacks
        ]
        if self.early_stopping:
            early_stopping = tf.keras.callbacks.EarlyStopping(
                patience=5, restore_best_weights=True)
            callbacks.append(early_stopping)
        if self.sparse_y:
            train_data = self._yield_data(X_train, Y_train, self.batch_size)
            val_data = self._yield_data(X_val, Y_val, self.batch_size)

            self.model.fit(
                x=train_data,
                steps_per_epoch=steps_per_epoch,
                validation_data=val_data,
                validation_steps=validation_steps,
                epochs=self.nb_epochs,
                callbacks=callbacks)
        else:
            self.model.fit(
                X_train,
                Y_train,
                epochs=self.nb_epochs,
                batch_size=self.batch_size,
                validation_data=(X_val, Y_val),
                callbacks=callbacks,
            )
        return self

    def predict(self, X):
        if self.sparse_y:
            Y_pred = []
            for i in range(0, X.shape[0], self.batch_size):
                X_batch = X[i: i+self.batch_size]
                Y_pred_batch = self.model(X_batch) > 0.5
                Y_pred.append(csr_matrix(Y_pred_batch))
            Y_pred = vstack(Y_pred)
            return Y_pred
        else:
            return self.model(X).numpy() > 0.5

    def predict_proba(self, X):
        if self.sparse_y:
            Y_pred_proba = []
            for i in range(0, X.shape[0], self.batch_size):
                X_batch = X[i: i+self.batch_size]
                Y_pred_proba_batch = self.model(X_batch)
                Y_pred_proba.append(csr_matrix(Y_pred_proba_batch))
            Y_pred_proba = vstack(Y_pred_proba)
            return Y_pred_proba
        else:
            return self.model(X).numpy()

    def score(self, X, Y):
        Y_pred = self.predict(X)
        return f1_score(Y_pred, Y, average="micro")

    def save(self, model_dir):
        self.model.save(model_dir)

    def load(self, model_dir):
        self.model = tf.keras.models.load_model(model_dir)
