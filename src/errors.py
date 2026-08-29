class IPOAgentError(Exception):
    """Base exception for expected pipeline failures."""


class ConfigurationError(IPOAgentError):
    pass


class DiscoveryError(IPOAgentError):
    pass


class MarketCalendarError(IPOAgentError):
    pass


class VerificationError(IPOAgentError):
    pass


class ProspectusError(IPOAgentError):
    pass


class EvidenceValidationError(IPOAgentError):
    pass


class LLMError(IPOAgentError):
    pass


class PDFGenerationError(IPOAgentError):
    pass


class EmailError(IPOAgentError):
    pass
