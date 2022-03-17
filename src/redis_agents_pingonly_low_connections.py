#!/usr/bin/python3
## pylint: disable = invalid-name, too-few-public-methods
from random import choices, randint, random
import os
import string
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

class RedisClient(object):
    def __init__(
        self,
        environment,
        url=configs["redis_url"],
    ):
        global redisClient
        self.rc = redisClient
        self.env = environment

    def __getattr__(self, name):
        func = self.rc.__getattribute__(name)

        def wrapper(*args, **kwargs):
            request_meta = {
                "request_type": "redis",
                "name": name,
                "start_time": time.time(),
                "response_length": 0,
                "exception": None,
                "context": None,
                "response": None,
            }
            start_perf_counter = time.perf_counter()
            ret = None
            try:
                ret = func(*args, **kwargs)
                request_meta["response"] = ret
            except Exception as e:
                request_meta["exception"] = e
            if type(request_meta["response"]) in [str,list,dict]:
                request_meta["response_length"] = len(request_meta["response"])
            else:
                request_meta["response_length"] = 1
            request_meta["response_time"] = (time.perf_counter() - start_perf_counter) * 1000
            self.env.events.request.fire(**request_meta)
            return ret
            
        return wrapper

# A locust User is an active agent with it's id and it uses GETSET every ~5/10 secs
class SysdigAgent(User):
    wait_time = constant(0)

    def __init__(self, environment):
        super(SysdigAgent, self).__init__(environment)
        self.client = RedisClient(environment=self.environment)
        #Generate agent id
        self.id=str(uuid.uuid4())

    # @task
    # def agentLock(self):
    #     setNXResult: bool = bool(self.client.setnx(self.id, 0))
    #     if setNXResult:
    #         # acquired
    #         logging.info("setNX is True")
    #         return
    #     self.client.get(self.id)
    #     if randint(1, 100) % 3  == 0:
    #         self.client.getset(self.id, 0)
    #         logging.info("expired: using getset")

    @task
    def ping(self):
        # This method is not found so __getattr_() will be called and 
        # the wrapper() will call the ping() method on the redis client
        self.client.ping()
