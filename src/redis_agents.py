#!/usr/bin/python3
## pylint: disable = invalid-name, too-few-public-methods
from random import choices, randint, random
import os
import time
import logging
import uuid
from locust import TaskSet, User, between, constant, events, task
from locust.runners import MasterRunner
import redis
import gevent.monkey

gevent.monkey.patch_all()

configs = {"redis_url": os.getenv("REDIS_URL")}
redisClient = None

# Initialize redis Client once per worker( one worker is approx one Sysdig Collector)
@events.init.add_listener
def on_locust_init(environment, **kwargs):
    global redisClient
    if not isinstance(environment.runner, MasterRunner):
        logging.info(f"Creating redis client {configs['redis_url']}")
        redisClient = redis.Redis.from_url(url=configs["redis_url"], ssl_cert_reqs=None)
        logging.info(f"info: {redisClient.info()}")

class RedisClient(object):
    def __init__(
        self,
        environment,
        url=configs["redis_url"],
    ):
        global redisClient
        self.rc = redisClient
        self.env = environment

    def get_set(self, key, value, command="GETSET"):
        request_meta = {
            "request_type": "GETSET",
            "name": key,
            "start_time": time.time(),
            "response_length": 0,
            "exception": None,
            "context": None,
            "response": None,
        }
        start_perf_counter = time.perf_counter()
        try:
            request_meta["response"] = str(self.rc.getset(key, value))
            request_meta["response_length"] = len(request_meta["response"])
        except Exception as e:
            request_meta["exception"] = e
        request_meta["response_time"] = (
            time.perf_counter() - start_perf_counter
        ) * 1000
        self.env.events.request.fire(**request_meta)
        return request_meta["response"]

# A locust User is an active agent with it's id and it uses GETSET every ~5/10 secs
class SysdigAgent(User):
    wait_time = constant(10)

    def __init__(self, environment):
        super(SysdigAgent, self).__init__(environment)
        self.client = RedisClient(environment=self.environment)

        #Generate agent id
        self.id=str(uuid.uuid1())

        #for i in range(self.max_agents):
        #    self.agents.append(str(uuid.uuid1()))

    @task
    def get_set(self):
        self.client.get_set(self.id, randint(1,60))