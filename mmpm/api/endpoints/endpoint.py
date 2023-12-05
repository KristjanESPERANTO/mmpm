#!/usr/bin/env python3
import json
from typing import Any

from flask import Response, jsonify
from mmpm.logger import MMPMLogger

logger = MMPMLogger.get_logger(__name__)


class Endpoint:
    def __init__(self):
        self.name: str = ""

    def success(self, msg: Any) -> Response:
        return jsonify({"code": 200, "message": msg})

    def failure(self, msg: Any, code: int = 500) -> Response:
        return jsonify({"code": code, "message": msg})
