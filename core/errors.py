from __future__ import annotations


class OfferFlowError(Exception):
    status_code = 500
    code = "OFFERFLOW_ERROR"


class ValidationError(OfferFlowError):
    status_code = 400
    code = "VALIDATION_ERROR"


class AuthenticationError(OfferFlowError):
    status_code = 401
    code = "AUTHENTICATION_REQUIRED"


class PermissionError(OfferFlowError):
    status_code = 403
    code = "FORBIDDEN"


class NotFoundError(OfferFlowError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(OfferFlowError):
    status_code = 409
    code = "CONFLICT"


class ExternalServiceError(OfferFlowError):
    status_code = 503
    code = "EXTERNAL_SERVICE_UNAVAILABLE"
