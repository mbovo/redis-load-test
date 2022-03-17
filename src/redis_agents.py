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

    def __getattr_(self, name):
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
            try:
                request_meta["response"] = func(*args, **kwargs)
            except Exception as e:
                request_meta["exception"] = e
            request_meta["response_length"] = len(request_meta["response"])
            request_meta["response_time"] = (time.perf_counter() - start_perf_counter) * 1000
            self.env.events.request.fire(**request_meta)
            return request_meta["response"]
            
        return wrapper

# WARNING this is no pythonic code, is a mere rewriting of java here 
# https://github.com/draios/backend/blob/da703f35ebaf088f45fdfa5e580a74fc68ff25b9/sysdig-backend/sysdig-lib/redis/src/main/java/com/sysdig/commons/services/LockService.java#L94
class Lock(object):
    def __init__(self, uuid:str, expiryTimeInMillis:float) -> None:
        self.uuid = uuid
        self.expiryTime = expiryTimeInMillis

    def fromString(text:str):
        split = text.split(":")
        return Lock(split[0],split[1])


    def __str__(self) -> str:
        return f"{self.uuid}:{self.expiryTime}" 
    
    def isExpired(self) -> bool:
        return self.expiryTime < (time.time()*1000)

    def isExpiredOrMine(self, otherUUID:str) -> bool:
        return self.isExpired() or self.uuid == otherUUID


# A locust User is an active agent with it's id and it uses GETSET every ~5/10 secs
class SysdigAgent(User):
    wait_time = constant(1)

    def __init__(self, environment):
        super(SysdigAgent, self).__init__(environment)
        self.client = RedisClient(environment=self.environment)

        #Generate agent id
        self.id=str(uuid.uuid1())

    @task(1)
    def agentLock(self):
        lockExpiryInMillis: float = 10.0 * 1000.0 # 10 secs in ms for this test

        newLock: Lock = Lock(self.id, (time.time()* 1000 )+ lockExpiryInMillis)

        setNXResult: bool = self.client.setnx(self.id, str(newLock))
        if setNXResult:
            # acquired
            return

        currentValue: str = str(self.client.get(self.id))
        if currentValue is not None:
            currentLock: Lock = Lock.fromString(currentValue)
            if currentLock.isExpiredOrMine(self.id):
                bounded = self.client.getset(str(newLock))
                # other code is not required from a redis POV

    @task(5)
    def ping(self):
        # This method is not found so __getattr_() will be called and 
        # the wrapper() will call the ping() method on the redis client
        self.client.ping()
