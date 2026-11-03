from django import forms

from apps.panel.selectors import cancellation_departments
from apps.panel.services.event_cancellations import CancellationSelection


class EventCancellationForm(forms.Form):
    left_date = forms.DateField(input_formats=["%Y-%m-%d"])
    right_date = forms.DateField(required=False, input_formats=["%Y-%m-%d"])
    departments = forms.ModelMultipleChoiceField(
        queryset=cancellation_departments(), required=False
    )

    def clean(self) -> dict[str, object]:
        cleaned = super().clean() or {}
        left_date = cleaned.get("left_date")
        right_date = cleaned.get("right_date") or left_date
        if left_date and right_date:
            try:
                CancellationSelection(left_date=left_date, right_date=right_date)
            except ValueError as exc:
                raise forms.ValidationError(str(exc)) from exc
        return cleaned

    def selection(self) -> CancellationSelection:
        return CancellationSelection(
            left_date=self.cleaned_data["left_date"],
            right_date=self.cleaned_data["right_date"] or self.cleaned_data["left_date"],
            department_ids=tuple(self.cleaned_data["departments"].values_list("pk", flat=True)),
        )
