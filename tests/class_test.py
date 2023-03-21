import sys  # just to see if it changes anything

class TestBase:
    def b(self, x):
        pass

    @classmethod
    def b_classm(cls, x):
        pass

    @staticmethod
    def b_static(x):
        pass

class Test(TestBase):
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

    @staticmethod
    def f_static(x):
        pass

    @classmethod
    def f_classm(cls, x):
        pass

def f5():
    def f6():
        pass

def f7():
    pass

if __name__ == "__main__":
    Test.Inner().f2(0)
