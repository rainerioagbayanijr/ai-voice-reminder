"""English display dates and explicit words for mixed-language speech."""

from datetime import date

MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
ORDINAL_DAYS = (
    "first",
    "second",
    "third",
    "fourth",
    "fifth",
    "sixth",
    "seventh",
    "eighth",
    "ninth",
    "tenth",
    "eleventh",
    "twelfth",
    "thirteenth",
    "fourteenth",
    "fifteenth",
    "sixteenth",
    "seventeenth",
    "eighteenth",
    "nineteenth",
    "twentieth",
    "twenty-first",
    "twenty-second",
    "twenty-third",
    "twenty-fourth",
    "twenty-fifth",
    "twenty-sixth",
    "twenty-seventh",
    "twenty-eighth",
    "twenty-ninth",
    "thirtieth",
    "thirty-first",
)
SMALL_NUMBERS = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")


def _number_words(number: int) -> str:
    if number < 20:
        return SMALL_NUMBERS[number]
    if number < 100:
        tens, ones = divmod(number, 10)
        return TENS[tens] + ("-" + SMALL_NUMBERS[ones] if ones else "")
    divisor, unit = (100, "hundred") if number < 1000 else (1000, "thousand")
    count, rest = divmod(number, divisor)
    return _number_words(count) + " " + unit + (" " + _number_words(rest) if rest else "")


def display_english_date(value: date) -> str:
    return f"{MONTHS[value.month - 1]} {value.day}, {value.year}"


def spoken_english_date(value: date) -> str:
    # Explicit words avoid the Filipino voice choosing Filipino number names.
    return f"{MONTHS[value.month - 1]} {ORDINAL_DAYS[value.day - 1]}, {_number_words(value.year)}"
