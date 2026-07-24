from rest_framework import serializers


class TripRequestSerializer(serializers.Serializer):
    # Field names intentionally match the JSON keys sent by TripFormData
    # in the React frontend (camelCase), so no renaming is needed on either side.
    currentLocation = serializers.CharField(max_length=255)
    pickupLocation = serializers.CharField(max_length=255)
    dropoffLocation = serializers.CharField(max_length=255)
    cycleUsedHours = serializers.FloatField(min_value=0, max_value=70)
