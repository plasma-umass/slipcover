import numpy as np
from numpy import linalg as LA

class Testme:
    def doit1(self, x):
    #    x = [i*i for i in range(1,1000)][0]
        y = 1
        x = [i*i for i in range(0,100000)][99999]
        y1 = [i*i for i in range(0,200000)][199999]
        z1 = [i for i in range(0,300000)][299999]
        z = x * y
    #    z = np.multiply(x, y)
        return z

    def doit2(self, x):
        i = 0
    #    zarr = [math.cos(13) for i in range(1,100000)]
    #    z = zarr[0]
        z = 0.1
        while i < 100000:
    #        z = math.cos(13)
    #        z = np.multiply(x,x)
    #        z = np.multiply(z,z)
    #        z = np.multiply(z,z)
            z = z * z
            z = x * x
            z = z * z
            z = z * z
            i += 1
        return z

    def doit3(self, x):
        z = x + 1
        z = x + 1
        z = x + 1
        z = x + z
        z = x + z
    #    z = np.cos(x)
        return z

    def stuff(self):
        y = np.random.randint(1, 100, size=5000000)[4999999]
        x = 1.01
        for i in range(1,10):
            print(i)
            for j in range(1,10):
                x = self.doit1(x)
                x = self.doit2(x)
                x = self.doit3(x)
                x = 1.01
        return x

if __name__ == "__main__":
    Testme().stuff()
