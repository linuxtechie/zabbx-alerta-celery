from setuptools import setup, find_packages

version = '0.0.1'

setup(
    name="zabbix-alerta-celery",
    version=version,
    description='Forward Zabbix events to Alerta via Celery',
    url='https://github.com/linuxtechie/zabbix-alerta-celery',
    license='MIT',
    author='Veeresh Khanorkar',
    author_email='veeresh@khanorkar.com',
    packages=find_packages(),
    py_modules=[
        'zabbix_alerta_celery'
    ],
    install_requires=[
        'celery',
        'alerta>=5.0.2',
        'pyzabbix',
        'protobix'
    ],
    include_package_data=True,
    zip_safe=True,
    entry_points={
        'console_scripts': [
            'zabbix-alerta-celery = zabbix_alerta_celery:main'
        ]
    },
    keywords='alert monitoring zabbix',
    classifiers=[
        'Topic :: System :: Monitoring'
    ]
)
