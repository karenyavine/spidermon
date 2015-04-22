import json


class SpidermonJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        from .managers import (RuleCheckResult, RuleDefinition, ActionRunResult, ActionDefinition)
        from .monitors import MonitorResult
        serializable_classes = (
            RuleCheckResult,
            RuleDefinition,
            ActionRunResult,
            ActionDefinition,
            MonitorResult,
        )
        if isinstance(obj, serializable_classes):
            return obj.to_json()
        else:
            return super(SpidermonJSONEncoder, self).default(obj)


class JSONSerializable(object):
    def json(self, indent=4):
        return json.dumps(self, indent=indent, sort_keys=True, cls=SpidermonJSONEncoder)

    def to_json(self):
        raise NotImplementedError
