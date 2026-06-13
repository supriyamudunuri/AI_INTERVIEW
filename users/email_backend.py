import ssl
from django.core.mail.backends.smtp import EmailBackend

class UnsafeSSLEmailBackend(EmailBackend):
    """
    Custom SMTP email backend that disables SSL certificate verification.
    Use only in development environments.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ssl_context = None
    
    @property
    def ssl_context(self):
        """Create SSL context with certificate verification disabled."""
        if self._ssl_context is None:
            self._ssl_context = ssl.create_default_context()
            self._ssl_context.check_hostname = False
            self._ssl_context.verify_mode = ssl.CERT_NONE
        return self._ssl_context
