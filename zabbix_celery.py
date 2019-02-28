import os, sys, argparse
import logging as LOG
from celery import Celery
from celery.utils.log import get_task_logger
from alertaclient.api import Client

celeryApp = Celery('zabbix-celery', broker='amqp://alerta:alerta@localhost//')

log = get_task_logger(__name__)

@celeryApp.task(autoretry_for=(Exception,), max_retries=None, retry_backoff=True)
def send2celery(endpoint, key, sslverify, alert):
  api = Client(endpoint=endpoint, key=key, ssl_verify=sslverify)
  api.send_alert(**alert)