"""Bounded load spreading; selected and server-required delays are never shortened."""
import random


def varied_delay(minimum,percent=25):
    minimum=max(0,float(minimum))
    percent=max(0,min(float(percent),100))
    return minimum+random.uniform(0,minimum*percent/100) if percent else minimum
