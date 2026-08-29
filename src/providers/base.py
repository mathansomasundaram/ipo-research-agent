from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from ..models import IPORecord


class IPOProvider(ABC):
    """Provider contract for discovering and enriching IPOs."""

    name: str

    @abstractmethod
    def get_upcoming_ipos(self, include_sme: bool = False) -> list[IPORecord]:
        raise NotImplementedError

    def get_ipos_opening_on(
        self,
        target_open_date: date,
        include_sme: bool = False,
    ) -> list[IPORecord]:
        return [
            ipo
            for ipo in self.get_upcoming_ipos(include_sme=include_sme)
            if ipo.open_date == target_open_date
        ]
