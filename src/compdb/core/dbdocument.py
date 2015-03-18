import logging
logger = logging.getLogger('compdb.core.dbdocument')

from queue import Queue

def sync_worker(stop_event, synced_or_failed_event,
                error_condition, queue, src, dst):
    from pymongo.errors import ConnectionFailure
    from queue import Empty
    while(not stop_event.is_set()):
        #src.sync()
        try:
            action, key = queue.get(timeout = 0.1)
            synced_or_failed_event.clear()
            logger.debug("syncing: {} {}".format(action, key))
            if action == 'set':
                dst[key] = src[key]
            elif action == 'get':
                src[key] = dst[key]
            elif action == 'del':
                del dst[key]
            elif action == 'clr':
                if src:
                    src.clear()
            else:
                raise RuntimeError("illegal sync action", action)
        except Empty:  # Only caught if we cleared the queue
            synced_or_failed_event.set()
            continue # Continue loop skipping 'task_done()'
        except KeyError: # This kind of error can be safely ignored
            pass
        except ConnectionFailure as error:
            logger.warning(error)           # This is not a problem, but
            error_condition.set()           # we need to know about this.
            synced_or_failed_event.set()
        except Exception as error:
            logger.error(error)             # This is likely a problem, but
            error_condition.set()           # the user will need to handle it.
            synced_or_failed_event.set()
        else:
            error_condition.clear()         # Handled the sync action without error.
        queue.task_done()

class ReadOnlyDBDocument(object):

    def __init__(self, host, db_name, collection_name, _id, rank = 0):
        from threading import Event, Condition
        from . mongodbdict import MongoDBDict
        self._id = _id
        self._rank = rank
        self._buffer = None
        self._mongodict = MongoDBDict(
            host, db_name, collection_name, _id)
        self._sync_queue = Queue()
        self._stop_event = Event()
        self._synced_or_failed_event = Event()
        self._sync_error_condition = Event()
        self._sync_thread = None
        msg = "Opened DBDocument '{}' on '{}'."
        logger.debug(msg.format(_id, collection_name))

    def _buffer_fn(self):
        return '{}.{}.sqlite'.format(self._id, self._rank)

    def __str__(self):
        return "{}(buffer='{}')".format(
            type(self).__name__,
            self._buffer_fn(),
            )

    def _get_buffer(self):
        if self._buffer is None:
            msg = "DBDocument not open!"
            raise RuntimeError(msg)
        return self._buffer

    def _join(self, timeout = 1.0):
        if self._sync_error_condition.is_set():
            return False
        else:
            return self._synced_or_failed_event.wait(timeout = timeout)

    def open(self):
        from sqlitedict import SqliteDict
        from threading import Thread
        logger.debug("Opening buffer...")
        self._buffer = SqliteDict(
            filename = self._buffer_fn(),
            tablename = 'dbdocument',
            autocommit = False)
        self._buffer.sync()
        logger.debug("Syncing buffer...")
        for key in self._buffer.keys():
            self._sync_queue.put(('set', key))
        self._sync_thread = Thread(
            target = sync_worker, 
            args = (self._stop_event, self._synced_or_failed_event,
                    self._sync_error_condition,
                    self._sync_queue, self._buffer, self._mongodict))
        self._stop_event.clear()
        self._sync_thread.start()
        return self

    def close(self, timeout = None):
        logger.debug("Closing and syncing...")
        self._join()
        self._stop_event.set()
        self._buffer.sync()
        self._sync_thread.join(timeout = timeout)
        if self._sync_thread.is_alive() or \
              self._sync_error_condition.is_set():
            logger.warning("Unable to sync to database.")
            self._buffer.close()
        else:
            logger.debug("Synced and closing.")
            self._buffer.close()
            # Deleting the underlying db file causes problems and
            # is probably unnecessary.
            #self._buffer.terminate() # Deleting the file causes

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, err_type, err_val, traceback):   
        try:
            self.close()
        except:
            return False
        else:
            return True

    def __getitem__(self, key):
        self._sync_queue.put(('get', key))
        self._join()
        return self._get_buffer()[key]
    
    def __iter__(self):
        self._join()
        return self._get_buffer().__iter__()

    def __contains__(self, key):
        self._sync_queue.put(('get', key))
        self._join()
        return self._get_buffer().__contains__(key)

    def get(self, key, default = None):
        self._sync_queue.put(('get', key))
        self._join()
        return self._get_buffer().get(key, default)

class DBDocument(ReadOnlyDBDocument):
    
    def __setitem__(self, key, value):
        self._get_buffer()[key] = value
        self._sync_queue.put(('set', key))

    def __delitem__(self, key):
        del self._get_buffer()[key]
        self._sync_queue.put(('del', key))

    def update(self, items=(), ** kwds):
        for key, value in kwds:
            self[key] = value
        for key, value in items:
            self[key] = value

    def clear(self):
        if self._sync_thread is not None:
            if self._sync_thread.is_alive():
                self._sync_queue.put(('clr', None))

    def remove(self):
        from pymongo.errors import ConnectionFailure
        import os
        try:
            self._mongodict.remove()
        except ConnectionFailure as error:
            logger.warning(error)
        try:
            self._buffer.terminate()
        except AttributeError:
            try:
                os.remove(self._buffer_fn())
            except OSError: pass
