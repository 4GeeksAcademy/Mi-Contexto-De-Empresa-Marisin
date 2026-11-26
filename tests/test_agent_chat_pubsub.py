"""Pub/sub en memoria del chat (`services/agent/chat/pubsub.py`): canal `chat.<session_id>` por sesión.

    python -m pytest tests/test_agent_chat_pubsub.py
"""

import asyncio
import threading

from services.agent.chat.pubsub import CLOSE, ChatPubSub, channel_name


def drain(subscription):
    items = []
    while not subscription.queue.empty():
        items.append(subscription.queue.get_nowait())
    return items


def test_the_channel_of_a_session_is_chat_dot_session_id():
    assert channel_name("chat_0219") == "chat.chat_0219"


def test_two_subscribers_of_the_same_channel_receive_the_same_events_in_order():
    async def scenario():
        pubsub = ChatPubSub()
        owner, supervisor = pubsub.subscribe("chat_a"), pubsub.subscribe("chat_a")
        for sequence in range(1, 6):
            assert pubsub.publish("chat_a", {"event": "token_chunk", "data": {"sequence": sequence}}) == 2
        await asyncio.sleep(0)
        return drain(owner), drain(supervisor)

    owner_items, supervisor_items = asyncio.run(scenario())

    assert [item["data"]["sequence"] for item in owner_items] == [1, 2, 3, 4, 5]
    assert supervisor_items == owner_items


def test_channels_are_isolated_between_sessions():
    async def scenario():
        pubsub = ChatPubSub()
        first, second = pubsub.subscribe("chat_a"), pubsub.subscribe("chat_b")
        pubsub.publish("chat_a", {"event": "token_chunk", "data": {"session_id": "chat_a"}})
        await asyncio.sleep(0)
        return drain(first), drain(second), pubsub.publish("chat_nobody", {"event": "x"})

    first_items, second_items, delivered = asyncio.run(scenario())

    assert [item["data"]["session_id"] for item in first_items] == ["chat_a"]
    assert second_items == []
    assert delivered == 0


def test_publish_from_another_thread_reaches_the_subscriber_loop_in_order():
    async def scenario():
        pubsub = ChatPubSub()
        subscription = pubsub.subscribe("chat_a")
        loop_thread = threading.get_ident()

        def agent_thread():  # el agente genera en un hilo, como `asyncio.to_thread(run_agent, …)`
            for sequence in range(1, 51):
                pubsub.publish("chat_a", {"event": "token_chunk", "data": {"sequence": sequence}})

        worker = threading.Thread(target=agent_thread)
        worker.start()
        received = [await asyncio.wait_for(subscription.queue.get(), timeout=2) for _ in range(50)]
        worker.join()
        return received, loop_thread == threading.get_ident()

    received, same_loop = asyncio.run(scenario())

    assert [item["data"]["sequence"] for item in received] == list(range(1, 51))
    assert same_loop


def test_a_full_queue_closes_only_that_subscriber():
    async def scenario():
        pubsub = ChatPubSub(queue_size=3)
        slow, healthy = pubsub.subscribe("chat_a"), pubsub.subscribe("chat_a")
        for sequence in range(1, 5):
            pubsub.publish("chat_a", {"event": "token_chunk", "data": {"sequence": sequence}})
            await asyncio.sleep(0)
            if sequence < 4:
                healthy.queue.get_nowait()  # este consumidor sí va leyendo
        pubsub.publish("chat_a", {"event": "token_chunk", "data": {"sequence": 5}})  # al cerrado ya no le llega
        await asyncio.sleep(0)
        return slow, healthy

    slow, healthy = asyncio.run(scenario())

    assert slow.closed is True
    assert drain(slow) == [CLOSE]  # la cola queda solo con la marca de cierre (el WS cierra con 1013)
    assert healthy.closed is False
    assert [item["data"]["sequence"] for item in drain(healthy)] == [4, 5]


def test_unsubscribe_cleans_up_the_channel():
    async def scenario():
        pubsub = ChatPubSub()
        first, second = pubsub.subscribe("chat_a"), pubsub.subscribe("chat_a")
        counts = [pubsub.subscriber_count("chat_a")]
        pubsub.unsubscribe(first)
        counts.append(pubsub.subscriber_count("chat_a"))
        pubsub.unsubscribe(second)
        counts.append(pubsub.subscriber_count("chat_a"))
        delivered = pubsub.publish("chat_a", {"event": "token_chunk"})
        await asyncio.sleep(0)
        return counts, delivered, first, second, pubsub

    counts, delivered, first, second, pubsub = asyncio.run(scenario())

    assert counts == [2, 1, 0]
    assert delivered == 0
    assert first.closed and second.closed
    assert drain(first) == [] and drain(second) == []
    assert pubsub._channels == {}
