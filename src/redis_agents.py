#!/usr/bin/python3
## pylint: disable = invalid-name, too-few-public-methods
from random import choices, randint, random
import os
import time
import string
import uuid
from locust import TaskSet, User, between, constant, events, task
import redis
import gevent.monkey

gevent.monkey.patch_all()

configs = {"redis_url": os.getenv("REDIS_URL")}


class RedisClient(object):
    def __init__(
        self,
        environment,
        url=configs["redis_url"],
    ):
        self.rc = redis.Redis.from_url(url=configs["redis_url"], ssl_cert_reqs=None)
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

class RedisLocust(User):
    wait_time = between(5,10)
    max_agents = int(os.getenv("AGENTS_COUNT"))
    agents = []

    def __init__(self, environment):
        super(RedisLocust, self).__init__(environment)
        self.client = RedisClient(environment=self.environment)

        for i in range(self.max_agents):
            self.agents.append(str(uuid.uuid1()))

    @task
    def get_set(self):
        for agent in self.agents:
            self.client.get_set(agent, randint(1, 60))