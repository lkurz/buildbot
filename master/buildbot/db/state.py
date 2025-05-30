# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members


import json

import sqlalchemy as sa
import sqlalchemy.exc
from twisted.internet import defer

from buildbot.db import base


class _IdNotFoundError(Exception):
    pass  # used internally


class ObjDict(dict):
    pass


class StateConnectorComponent(base.DBConnectorComponent):
    @defer.inlineCallbacks
    def getObjectId(self, name, class_name):
        # defer to a cached method that only takes one parameter (a tuple)
        objdict = yield self._getObjectId((name, class_name))
        return objdict['id']

    # returns a Deferred that returns a value
    @base.cached('objectids')
    def _getObjectId(self, name_class_name_tuple):
        name, class_name = name_class_name_tuple

        def thd(conn):
            return self.thdGetObjectId(conn, name, class_name)

        return self.db.pool.do(thd)

    def thdGetObjectId(self, conn, name, class_name):
        objects_tbl = self.db.model.objects

        name = self.ensureLength(objects_tbl.c.name, name)
        self.checkLength(objects_tbl.c.class_name, class_name)

        def select():
            q = sa.select(objects_tbl.c.id).where(
                objects_tbl.c.name == name,
                objects_tbl.c.class_name == class_name,
            )
            res = conn.execute(q)
            row = res.fetchone()
            res.close()
            if not row:
                raise _IdNotFoundError
            return row.id

        def insert():
            res = conn.execute(objects_tbl.insert().values(name=name, class_name=class_name))
            conn.commit()
            return res.inserted_primary_key[0]

        # we want to try selecting, then inserting, but if the insert fails
        # then try selecting again.  We include an invocation of a hook
        # method to allow tests to exercise this particular behavior
        try:
            return ObjDict(id=select())
        except _IdNotFoundError:
            pass

        self._test_timing_hook(conn)

        try:
            return ObjDict(id=insert())
        except (sqlalchemy.exc.IntegrityError, sqlalchemy.exc.ProgrammingError):
            conn.rollback()

        return ObjDict(id=select())

    class Thunk:
        pass

    # returns a Deferred that returns a value
    def getState(self, objectid, name, default=Thunk):
        def thd(conn):
            return self.thdGetState(conn, objectid, name, default=default)

        return self.db.pool.do(thd)

    def thdGetState(self, conn, objectid, name, default=Thunk):
        object_state_tbl = self.db.model.object_state

        q = sa.select(
            object_state_tbl.c.value_json,
        ).where(
            object_state_tbl.c.objectid == objectid,
            object_state_tbl.c.name == name,
        )
        res = conn.execute(q)
        row = res.fetchone()
        res.close()

        if not row:
            if default is self.Thunk:
                raise KeyError(f"no such state value '{name}' for object {objectid}")
            return default
        try:
            return json.loads(row.value_json)
        except ValueError as e:
            raise TypeError(f"JSON error loading state value '{name}' for {objectid}") from e

    # returns a Deferred that returns a value
    def setState(self, objectid, name, value):
        def thd(conn):
            return self.thdSetState(conn, objectid, name, value)

        return self.db.pool.do(thd)

    def thdSetState(self, conn, objectid, name, value):
        object_state_tbl = self.db.model.object_state

        try:
            value_json = json.dumps(value)
        except (TypeError, ValueError) as e:
            raise TypeError(f"Error encoding JSON for {value!r}") from e

        name = self.ensureLength(object_state_tbl.c.name, name)

        def update():
            q = object_state_tbl.update().where(
                object_state_tbl.c.objectid == objectid, object_state_tbl.c.name == name
            )
            res = conn.execute(q.values(value_json=value_json))
            conn.commit()

            # check whether that worked
            return res.rowcount > 0

        def insert():
            conn.execute(
                object_state_tbl.insert().values(
                    objectid=objectid, name=name, value_json=value_json
                )
            )
            conn.commit()

        # try updating; if that fails, try inserting; if that fails, then
        # we raced with another instance to insert, so let that instance
        # win.

        if update():
            return

        self._test_timing_hook(conn)

        try:
            insert()
        except (sqlalchemy.exc.IntegrityError, sqlalchemy.exc.ProgrammingError):
            conn.rollback()  # someone beat us to it - oh well

    def _test_timing_hook(self, conn):
        # called so tests can simulate another process inserting a database row
        # at an inopportune moment
        pass

    # returns a Deferred that returns a value
    def atomicCreateState(self, objectid, name, thd_create_callback):
        def thd(conn):
            object_state_tbl = self.db.model.object_state
            res = self.thdGetState(conn, objectid, name, default=None)
            if res is None:
                res = thd_create_callback()
                try:
                    value_json = json.dumps(res)
                except (TypeError, ValueError) as e:
                    raise TypeError(f"Error encoding JSON for {res!r}") from e
                self._test_timing_hook(conn)
                try:
                    conn.execute(
                        object_state_tbl.insert().values(
                            objectid=objectid,
                            name=name,
                            value_json=value_json,
                        )
                    )
                    conn.commit()
                except (sqlalchemy.exc.IntegrityError, sqlalchemy.exc.ProgrammingError):
                    conn.rollback()
                    # someone beat us to it - oh well return that value
                    return self.thdGetState(conn, objectid, name)
            return res

        return self.db.pool.do(thd)
