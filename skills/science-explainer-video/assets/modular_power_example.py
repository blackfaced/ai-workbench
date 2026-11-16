"""分镜示例的可运行科学核验：从最高位开始的二进制模幂。

只支持非负整数指数、正整数模数。分别统计平方和额外相乘，
两者都含一次模约减；不把大整数乘法的位成本当成常数。
"""


def binary_modular_power(base, exponent, modulus):
    if exponent < 0 or modulus < 1:
        raise ValueError("requires exponent >= 0 and modulus >= 1")
    if exponent == 0:
        return 1 % modulus, 0, 0
    base %= modulus
    value = base
    squares = multiplies = 0
    for bit in bin(exponent)[3:]:  # skip '0b' and the leading 1
        value = value * value % modulus
        squares += 1
        if bit == "1":
            value = value * base % modulus
            multiplies += 1
    return value, squares, multiplies


def verify():
    # Independent oracle and boundaries: zero exponent, modulus 1, negative bases.
    for base in (-3, 0, 2, 5):
        for exponent in range(64):
            for modulus in (1, 7, 97):
                assert binary_modular_power(base, exponent, modulus)[0] == pow(base, exponent, modulus)
    assert binary_modular_power(2, 13, 97) == (44, 3, 2)
    value, squares, multiplies = binary_modular_power(2, 10**9, 97)
    assert value == pow(2, 10**9, 97) == 61
    assert (squares, multiplies) == (29, 12)
    print("PASS: 768 small cases; 2^13 mod 97 = 44 (3 squares + 2 multiplies)")
    print("2^1000000000 mod 97 = 61 (29 squares + 12 multiplies = 41)")


if __name__ == "__main__":
    verify()
