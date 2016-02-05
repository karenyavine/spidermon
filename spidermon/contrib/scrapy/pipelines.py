import six
import json
import StringIO
from collections import defaultdict

from scrapy.exceptions import DropItem, NotConfigured
from scrapy.utils.misc import load_object
from scrapy.exporters import JsonLinesItemExporter
from scrapy import Field

from spidermon.contrib.validation import SchematicsValidator, JSONSchemaValidator
from schematics.models import Model

from .stats import ValidationStatsManager


DEFAULT_ERRORS_FIELD = '_validation'
DEFAULT_ADD_ERRORS_TO_ITEM = False
DEFAULT_DROP_ITEMS_WITH_ERRORS = False


class UniversalItem(object):
    pass


class ItemValidationPipeline(object):

    def __init__(self, validators, stats,
                 drop_items_with_errors=DEFAULT_DROP_ITEMS_WITH_ERRORS,
                 add_errors_to_items=DEFAULT_ADD_ERRORS_TO_ITEM,
                 errors_field=None):
        self.drop_items_with_errors = drop_items_with_errors
        self.add_errors_to_items = add_errors_to_items or DEFAULT_ADD_ERRORS_TO_ITEM
        self.errors_field = errors_field or DEFAULT_ERRORS_FIELD
        self.validators = validators
        self.stats = ValidationStatsManager(stats)
        for _type, vals in validators.items():
            [self.stats.add_validator(_type, val.name) for val in vals]

    @classmethod
    def from_crawler(cls, crawler):
        validators = {}
        allowed_types = (list, tuple, dict)

        def set_validators(loader, schema):
            if type(schema) in (list, tuple):
                schema = {UniversalItem: schema}
            for obj, paths in schema.items():
                key = obj.__name__
                paths = paths if type(paths) in (list, tuple) else [paths]
                objects = [loader(v) for v in paths]
                validators[key] = validators.get(key, []) + objects

        for loader, name in [
            (cls._load_jsonschema_validator, 'SPIDERMON_VALIDATION_SCHEMAS'),
            (cls._load_schematics_validator, 'SPIDERMON_VALIDATION_MODELS'),
        ]:
            res = crawler.settings.get(name)
            if not res:
                continue
            if type(res) not in allowed_types:
                raise NotConfigured('Invalid <{}> type for <{}> settings, dict or list/tuple'
                                    'is required'.format(type(res), name))
            set_validators(loader, res)
        return cls(
            validators=validators,
            stats=crawler.stats,
            drop_items_with_errors=crawler.settings.get('SPIDERMON_VALIDATION_DROP_ITEMS_WITH_ERRORS'),
            add_errors_to_items=crawler.settings.get('SPIDERMON_VALIDATION_ADD_ERRORS_TO_ITEMS'),
            errors_field=crawler.settings.get('SPIDERMON_VALIDATION_ERRORS_FIELD'),
        )

    @classmethod
    def _load_jsonschema_validator(cls, schema):
        if isinstance(schema, six.string_types):
            if schema.endswith('.json'):
                with open(schema, 'r') as f:
                    schema = json.load(f)
            else:
                schema = load_object(schema)
                if isinstance(schema, six.string_types):
                    schema = json.loads(schema)
        if not isinstance(schema, dict):
            raise NotConfigured('Invalid schema, jsonschemas must be defined as:\n'
                                '- a python dict.\n'
                                '- an object path to a python dict.\n'
                                '- an object path to a JSON string.\n'
                                '- a path to a JSON file.')
        return JSONSchemaValidator(schema)

    @classmethod
    def _load_schematics_validator(cls, model_path):
        model_class = load_object(model_path)
        if not issubclass(model_class, Model):
            raise NotConfigured('Invalid model, models must subclass schematics.models.Model')
        return SchematicsValidator(model_class)

    def process_item(self, item, _):
        data = self._convert_item_to_dict(item)
        self.stats.add_item()
        self.stats.add_fields(len(data.keys()))
        for validator in self.find_validators(item):
            ok, errors = validator.validate(data)
            if not ok:
                for field_name, messages in errors.items():
                    for message in messages:
                        self.stats.add_field_error(field_name, message)
                self.stats.add_item_with_errors()
                if self.add_errors_to_items:
                    self._add_errors_to_item(item, errors)
                if self.drop_items_with_errors:
                    self.stats.add_dropped_item()
                    raise DropItem('Validation failed!')
        return item

    def find_validators(self, item):
        find = lambda x: self.validators.get(x.__name__, [])
        return find(item.__class__) + find(UniversalItem)

    def _convert_item_to_dict(self, item):
        serialized_json = StringIO.StringIO()
        JsonLinesItemExporter(serialized_json).export_item(item)
        data = json.loads(serialized_json.getvalue())
        serialized_json.close()
        return data

    def _add_errors_to_item(self, item, errors):
        if not self.errors_field in item.__class__.fields:
            item.__class__.fields[self.errors_field] = Field()
        if not self.errors_field in item._values:
            item[self.errors_field] = defaultdict(list)
        for field_name, messages in errors.items():
            item[self.errors_field][field_name] += messages

