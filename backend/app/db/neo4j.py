from typing import Any

from fastapi import Request
from neo4j import AsyncGraphDatabase
from neo4j.exceptions import AuthError, DriverError, Neo4jError, ServiceUnavailable


class Neo4jClient:
    def __init__(self, uri: str, username: str, password: str, database: str) -> None:
        self._database = database
        self._driver = AsyncGraphDatabase.driver(uri, auth=(username, password))

    def session(self) -> Any:
        return self._driver.session(database=self._database)

    async def ping(self) -> bool:
        try:
            async with self.session() as session:
                result = await session.run("RETURN 1 AS result")
                record = await result.single()
                return record is not None and record.get("result") == 1
        except (AuthError, DriverError, Neo4jError, ServiceUnavailable, OSError, TimeoutError):
            return False

    async def close(self) -> None:
        await self._driver.close()


def get_neo4j_client(request: Request) -> Neo4jClient:
    return request.app.state.neo4j
