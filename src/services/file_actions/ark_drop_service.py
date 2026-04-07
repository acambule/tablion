from __future__ import annotations

from typing import Callable


class ArkDropService:
    def start_extract(
        self,
        *,
        service: str,
        object_path: str,
        destination: str,
        qdbus_connection,
        qdbus_message_cls,
        qdbus_pending_call_watcher_cls,
        parent,
        watcher_store: set,
        finish_callback: Callable,
        process_cls,
        timer_cls,
        logger: Callable[[str], None] | None = None,
    ) -> bool:
        if not destination:
            return False

        if qdbus_connection is not None and qdbus_message_cls is not None and qdbus_pending_call_watcher_cls is not None:
            message = qdbus_message_cls.createMethodCall(
                service,
                object_path,
                "org.kde.ark.DndExtract",
                "extractSelectedFilesTo",
            )
            message.setArguments([destination])
            pending_call = qdbus_connection.sessionBus().asyncCall(message)
            watcher = qdbus_pending_call_watcher_cls(pending_call, parent)
            watcher_store.add(watcher)

            def on_finished(*_args):
                reply = watcher.reply()
                if reply.type() == qdbus_message_cls.MessageType.ErrorMessage:
                    finish_callback(
                        watcher=watcher,
                        error_message="Ark konnte die Auswahl nicht extrahieren.",
                    )
                    return
                finish_callback(watcher=watcher)

            watcher.finished.connect(on_finished)
            if logger is not None:
                logger(f"DND Ark extract started via QtDBus: service={service!r} path={object_path!r} target={destination!r}")
            return True

        for program in ("qdbus6", "qdbus"):
            executable = process_cls()
            executable.start(program, [service, object_path, "org.kde.ark.DndExtract.extractSelectedFilesTo", destination])
            if not executable.waitForStarted(250):
                continue
            executable.waitForFinished(5000)
            if executable.exitStatus() == process_cls.ExitStatus.NormalExit and executable.exitCode() == 0:
                if logger is not None:
                    logger(f"DND Ark extract started via {program}: service={service!r} path={object_path!r} target={destination!r}")
                timer_cls.singleShot(800, lambda: finish_callback())
                return True

        if logger is not None:
            logger("DND Ark extract failed: no QtDBus and no qdbus fallback available")
        return False
