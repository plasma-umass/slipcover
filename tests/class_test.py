import sys  # just to see if it changes anything

class Test:
    def f1(self, x):
        pass

    class Inner:
        def f2(self, x):
            pass

        def f3(self, x):
            pass

        class InnerInner:
            def f4(self, x):
                pass

def f5():
    def f6():
        pass

def f7():
    pass

if __name__ == "__main__":
    Test.Inner().f2(0)
