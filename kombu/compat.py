"""
kombu.compat
============

Carrot compatible interface for :class:`Publisher` and :class:`Producer`.

See http://packages.python.org/pypi/carrot for documentation.

:copyright: (c) 2009 - 2011 by Ask Solem.
:license: BSD, see LICENSE for more details.

"""
from itertools import count

from kombu import entity
from kombu import messaging


def _iterconsume(connection, consumer, no_ack=False, limit=None):
    consumer.consume(no_ack=no_ack)
    for iteration in count(0):
        if limit and iteration >= limit:
            raise StopIteration
        yield connection.drain_events()


def entry_to_queue(queue, **options):
    binding_key = options.get("binding_key") or options.get("routing_key")

    e_durable = options.get("exchange_durable")
    if e_durable is None:
        e_durable = options.get("durable")

    e_auto_delete = options.get("exchange_auto_delete")
    if e_auto_delete is None:
        e_auto_delete = options.get("auto_delete")

    q_durable = options.get("queue_durable")
    if q_durable is None:
        q_durable = options.get("durable")

    q_auto_delete = options.get("queue_auto_delete")
    if q_auto_delete is None:
        q_auto_delete = options.get("auto_delete")

    e_arguments = options.get("exchange_arguments")
    q_arguments = options.get("queue_arguments")
    b_arguments = options.get("binding_arguments")

    exchange = entity.Exchange(options.get("exchange"),
                               type=options.get("exchange_type"),
                               delivery_mode=options.get("delivery_mode"),
                               routing_key=options.get("routing_key"),
                               durable=e_durable,
                               auto_delete=e_auto_delete,
                               arguments=e_arguments)

    return entity.Queue(queue,
                        exchange=exchange,
                        routing_key=binding_key,
                        durable=q_durable,
                        exclusive=options.get("exclusive"),
                        auto_delete=q_auto_delete,
                        no_ack=options.get("no_ack"),
                        queue_arguments=q_arguments,
                        binding_arguments=b_arguments)


class Publisher(messaging.Producer):
    exchange = ""
    exchange_type = "direct"
    routing_key = ""
    durable = True
    auto_delete = False
    _closed = False

    def __init__(self, connection, exchange=None, routing_key=None,
            exchange_type=None, durable=None, auto_delete=None, **kwargs):
        self.connection = connection
        self.backend = connection.channel()

        self.exchange = exchange or self.exchange
        self.exchange_type = exchange_type or self.exchange_type
        self.routing_key = routing_key or self.routing_key

        if auto_delete is not None:
            self.auto_delete = auto_delete
        if durable is not None:
            self.durable = durable

        if not isinstance(self.exchange, entity.Exchange):
            self.exchange = entity.Exchange(name=self.exchange,
                                            type=self.exchange_type,
                                            routing_key=self.routing_key,
                                            auto_delete=self.auto_delete,
                                            durable=self.durable)

        super(Publisher, self).__init__(self.backend, self.exchange,
                **kwargs)

    def send(self, *args, **kwargs):
        return self.publish(*args, **kwargs)

    def revive(self, channel):
        self.backend = channel
        super(Publisher, self).revive(channel)

    def close(self):
        self.backend.close()
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()


class Consumer(messaging.Consumer):
    queue = ""
    exchange = ""
    routing_key = ""
    exchange_type = "direct"
    durable = True
    exclusive = False
    auto_delete = False
    exchange_type = "direct"
    _closed = False

    def __init__(self, connection, queue=None, exchange=None,
            routing_key=None, exchange_type=None, durable=None,
            exclusive=None, auto_delete=None, **kwargs):
        self.connection = connection
        self.backend = connection.channel()

        if durable is not None:
            self.durable = durable
        if exclusive is not None:
            self.exclusive = exclusive
        if auto_delete is not None:
            self.auto_delete = auto_delete

        self.queue = queue or self.queue
        self.exchange = exchange or self.exchange
        self.exchange_type = exchange_type or self.exchange_type
        self.routing_key = routing_key or self.routing_key

        exchange = entity.Exchange(self.exchange,
                                   type=self.exchange_type,
                                   routing_key=self.routing_key,
                                   auto_delete=self.auto_delete,
                                   durable=self.durable)
        queue = entity.Queue(self.queue,
                             exchange=exchange,
                             routing_key=self.routing_key,
                             durable=self.durable,
                             exclusive=self.exclusive,
                             auto_delete=self.auto_delete)
        super(Consumer, self).__init__(self.backend, queue, **kwargs)

    def revive(self, channel):
        self.backend = channel
        super(Consumer, self).revive(channel)

    def close(self):
        self.cancel()
        self.backend.close()
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    def __iter__(self):
        return self.iterqueue(infinite=True)

    def fetch(self, no_ack=None, enable_callbacks=False):
        if no_ack is None:
            no_ack = self.no_ack
        message = self.queues[0].get(no_ack)
        if message:
            if enable_callbacks:
                self.receive(message.payload, message)
        return message

    def process_next(self):
        raise NotImplementedError("Use fetch(enable_callbacks=True)")

    def discard_all(self, filterfunc=None):
        if filterfunc is not None:
            raise NotImplementedError(
                    "discard_all does not implement filters")
        return self.purge()

    def iterconsume(self, limit=None, no_ack=None):
        return _iterconsume(self.connection, self, no_ack, limit)

    def wait(self, limit=None):
        it = self.iterconsume(limit)
        return list(it)

    def iterqueue(self, limit=None, infinite=False):
        for items_since_start in count():
            item = self.fetch()
            if (not infinite and item is None) or \
                    (limit and items_since_start >= limit):
                raise StopIteration
            yield item


class ConsumerSet(messaging.Consumer):

    def __init__(self, connection, from_dict=None, consumers=None,
            callbacks=None, **kwargs):
        self.connection = connection
        self.backend = connection.channel()

        queues = []
        if consumers:
            for consumer in consumers:
                queues.extend(consumer.queues)
        if from_dict:
            for queue_name, queue_options in from_dict.items():
                queues.append(entry_to_queue(queue_name, **queue_options))

        super(ConsumerSet, self).__init__(self.backend, queues, **kwargs)

    def iterconsume(self, limit=None, no_ack=False):
        return _iterconsume(self.connection, self, no_ack, limit)

    def discard_all(self):
        return self.purge()

    def add_consumer_from_dict(self, queue, **options):
        queue = entry_to_queue(queue, **options)(self.channel)
        if self.auto_declare:
            queue.declare()
        self.queues.append(queue)
        return queue

    def add_consumer(self, consumer):
        for queue in consumer.queues:
            self.queues.append(queue(self.channel))

    def revive(self, channel):
        self.backend = channel
        super(ConsumerSet, self).revive(channel)

    def close(self):
        self.cancel()
        self.channel.close()
