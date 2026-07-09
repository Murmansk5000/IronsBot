# SPDX-License-Identifier: GPL-3.0-or-later
from collections import defaultdict
from typing import Generic

from typing_extensions import Unpack

from ..type_hint import Listener, T_Args, T_Key


class EventListener(Generic[T_Key, Unpack[T_Args]]):
    def __init__(self) -> None:
        self._listeners: defaultdict[T_Key, list[Listener[Unpack[T_Args]]]] = (
            defaultdict(list)
        )
        self._disposable: set[int] = set()

    def add_listener(
        self,
        event_id: T_Key,
        callback: Listener[Unpack[T_Args]],
        disposable: bool = False,
    ) -> Listener[Unpack[T_Args]]:
        if disposable:
            self._disposable.add(id(callback))
        self._listeners[event_id].append(callback)
        return callback

    def remove_listener(
        self, event_id: T_Key, callback: Listener[Unpack[T_Args]]
    ) -> None:
        if event_id in self._listeners:
            self._listeners[event_id].remove(callback)
            self._disposable.discard(id(callback))
            if not self._listeners[event_id]:
                del self._listeners[event_id]

    def trigger(self, event_id: T_Key, *args: Unpack[T_Args]) -> None:
        listeners = self._listeners[event_id]
        i = 0
        while i < len(listeners):
            listener = listeners[i]
            listener(*args)
            if id(listener) in self._disposable:
                self.remove_listener(event_id, listener)
            else:
                i += 1
