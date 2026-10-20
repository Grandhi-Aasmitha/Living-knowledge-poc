# Atlas Architecture Demo

## Billing flow

Atlas Operations Team owns Atlas Billing Service.
Atlas Billing Service depends on Atlas Orders Database.
Atlas Billing Service calls Atlas Payments API.
Atlas Billing Service produces Atlas Invoice Topic.
Atlas Alerting Service calls Atlas Billing Service.

## Dispatch flow

Atlas Dispatch Service consumes Atlas Dispatch Topic.

## Reports ownership record from Operations

Atlas Operations Team owns Atlas Reports Service.

## Reports ownership record from Platform

Atlas Platform Team owns Atlas Reports Service.
