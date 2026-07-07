import logging
from celery import Celery
from celery.signals import task_failure, task_revoked
import traceback

logger = logging.getLogger(__name__)

import os

def make_celery() -> Celery:
    """Create and configure Celery app."""
    celery_app = Celery('real_estate_scraper')
    
    redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    
    # Configurações básicas do Celery
    celery_app.conf.update(
        broker_url=redis_url,
        result_backend=redis_url,
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,
        worker_prefetch_multiplier=1,
        task_acks_late=True,
        # Configurações de retry
        task_reject_on_worker_lost=True,
        task_track_started=True,
    )
    
    # Configuração de retries para tarefas críticas
    celery_app.conf.task_default_retry_delay = 30
    celery_app.conf.task_default_max_retries = 3
    
    return celery_app

# Sinal para tratamento de falhas em tarefas
@task_failure.connect
def handle_task_failure(sender=None, task_id=None, exception=None, traceback=None, **kwargs):
    """Handle task failures with detailed logging."""
    try:
        logger.error(
            "Task failed",
            extra={
                'task_id': task_id,
                'task_name': sender.name if sender else 'unknown',
                'exception': str(exception),
                'traceback': traceback,
                'args': kwargs.get('args', []),
                'kwargs': kwargs.get('kwargs', {})
            }
        )
    except Exception as e:
        logger.error(f"Error in task failure handler: {e}")

# Sinal para tratamento de tarefas revogadas
@task_revoked.connect
def handle_task_revoked(sender=None, request=None, terminated=None, signum=None, expired=None, **kwargs):
    """Handle revoked tasks."""
    try:
        logger.warning(
            "Task revoked",
            extra={
                'task_id': request.id if request else 'unknown',
                'task_name': sender.name if sender else 'unknown',
                'terminated': terminated,
                'signum': signum,
                'expired': expired
            }
        )
    except Exception as e:
        logger.error(f"Error in task revoked handler: {e}")
