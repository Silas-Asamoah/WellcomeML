from .entity_linking import EntityLinker
from .knowledge_base import PeopleKB

from wellcomeml.logger import logger

try:
    from .bert_classifier import BertClassifier
    from .bert_vectorizer import BertVectorizer
    from .vectorizer import Vectorizer
    from .spacy_ner import SpacyNER
    from .spacy_classifier import SpacyClassifier
except ImportError:
    logger.warning("Using WellcomeML without extras (transformers & torch).")